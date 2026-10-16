"""Gerenciador do banco de dados da biblioteca local."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from ytmusic_tui.config import settings
from ytmusic_tui.library import migrations
from ytmusic_tui.library.errors import translate_db_error
from ytmusic_tui.library.models import Base
from ytmusic_tui.permissions import secure_file


def _secure_db_files(db_path: Path) -> None:
    """0600 no banco e nos sidecars WAL/SHM (§8.3/T06).

    O SQLite cria os arquivos com o modo do umask do processo; o ajuste é só
    "apertar" (nunca afrouxa o que o usuário escolheu) e é barato (stat)
    quando o modo já está certo. Ausentes → no-op.
    """
    for candidate in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        secure_file(candidate, label="banco da biblioteca")


@dataclass(frozen=True)
class IntegrityReport:
    """Resultado de ``PRAGMA integrity_check`` (T05-R5, insumo da T13)."""

    ok: bool
    messages: tuple[str, ...]
    db_path: Path


class DatabaseManager:
    """Gerencia conexão e sessões do banco de dados SQLite."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or settings.library_db_path
        self._engine: Engine | None = None
        self._session_factory: sessionmaker | None = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    def _create_engine(self) -> Engine:
        """Cria engine SQLite com configurações otimizadas."""
        # SQLite com WAL mode para melhor concorrência
        db_url = f"sqlite:///{self.db_path}"

        engine = create_engine(
            db_url,
            # Pool padrão (QueuePool): uma conexão por vez para cada thread
            # (UI e worker de download). WAL + timeout absorvem a concorrência.
            connect_args={
                "check_same_thread": False,
                "timeout": 30,
            },
        )

        # Habilitar WAL mode e foreign keys
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-32768")  # 32MB cache
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()
            # §8.3/T06: dados da biblioteca são privados (o arquivo e os
            # sidecars WAL/SHM nascem com o modo do umask).
            _secure_db_files(self.db_path)

        return engine

    @property
    def session_factory(self) -> sessionmaker:
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                expire_on_commit=False,
                autoflush=True,
                autocommit=False,
            )
        return self._session_factory

    def create_all(self) -> None:
        """Cria todas as tabelas do esquema atual (sem versionar).

        Atalho de teste/utilitário: o app abre o banco por ``migrate()``,
        que decide entre banco novo, legado e incompatível (T05-R1).
        """
        Base.metadata.create_all(self.engine)

    def migrate(self) -> migrations.MigrationOutcome:
        """Abre o banco na versão do esquema do código (T05-R1/R2).

        Banco novo nasce no esquema atual e estampado; banco legado ganha
        backup antes de qualquer DDL e migra sem apagar dados; esquema mais
        novo (ou arquivo alheio) → ``SchemaIncompatibleError``, sem tocar em
        nada. Devolve o resumo para log/testes.
        """
        outcome = migrations.migrate(self.engine, db_path=self.db_path)
        # Depois das DDLs os sidecars WAL/SHM já existem; aperta de novo
        # (§8.3/T06) — o evento de connect roda antes das primeiras escritas.
        _secure_db_files(self.db_path)
        return outcome

    def schema_version(self) -> int | None:
        """Versão do esquema persistida (``None`` se o banco não é nosso)."""
        return migrations.read_schema_version(self.engine, db_path=self.db_path)

    def integrity_check(self) -> IntegrityReport:
        """``PRAGMA integrity_check`` para diagnóstico (T05-R5/T13).

        Banco saudável devolve ``ok=True``; corrupção que impede a leitura
        vira ``DatabaseCorruptError`` (tipado). Nunca altera o banco.
        """
        try:
            with self.engine.connect() as connection:
                rows = [
                    str(row[0])
                    for row in connection.execute(text("PRAGMA integrity_check")).fetchall()
                ]
        except Exception as error:
            translated = translate_db_error(error, self.db_path)
            if translated is not None:
                raise translated from error
            raise
        return IntegrityReport(ok=rows == ["ok"], messages=tuple(rows), db_path=self.db_path)

    def drop_all(self) -> None:
        """Remove todas as tabelas (cuidado!)."""
        Base.metadata.drop_all(self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Context manager para sessão com commit/rollback automático.

        Toda falha do sqlite3 é traduzida para erro tipado (T05-R4) — a
        camada de cima decide a mensagem pelo tipo, sem conhecer sqlite3.
        Restrições (``IntegrityError``) sobem como estão: são do domínio.
        """
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception as error:
            session.rollback()
            translated = translate_db_error(error, self.db_path)
            if translated is not None:
                raise translated from error
            raise
        finally:
            session.close()

    def close(self) -> None:
        """Fecha engine e conexões."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None


# Instância global
db_manager = DatabaseManager()
