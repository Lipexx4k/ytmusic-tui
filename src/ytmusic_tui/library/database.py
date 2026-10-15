"""Gerenciador do banco de dados da biblioteca local."""
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ytmusic_tui.config import settings
from ytmusic_tui.library.models import Base


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
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-32768")  # 32MB cache
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()

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
        """Cria todas as tabelas."""
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        """Remove todas as tabelas (cuidado!)."""
        Base.metadata.drop_all(self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Context manager para sessão com commit/rollback automático."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
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