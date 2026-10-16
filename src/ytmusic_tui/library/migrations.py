"""Migrações versionadas do esquema da biblioteca (§7/T05-R1/R2).

Mecanismo próprio e mínimo — a alternativa era o Alembic, que puxaria
dependência nova (e rede) para um histórico aditivo e pequeno; aqui a
versão do esquema fica **no próprio banco** (tabela ``schema_migrations``,
uma linha por versão aplicada) e cada passo roda em UMA transação: falhou,
volta tudo.

Três situações na abertura do banco:

- **novo/vazio**: nasce no esquema atual (``create_all``) e estampado na
  versão corrente — nunca "migra do zero";
- **legado T01–T04** (tem ``tracks``, sem ``schema_migrations``):
  reconhecido pelo esquema, ganha backup ANTES de qualquer DDL e aplica as
  migrações pendentes sem apagar dados;
- **mais novo que o app ou arquivo alheio**: ``SchemaIncompatibleError``,
  nada é tocado — ``create_all`` silencioso nunca acontece.

Há SQL cru aqui de propósito (exceção explícita do R7): é DDL e
contabilidade de esquema, não consulta de domínio — as consultas continuam
todas em ``library/service.py`` e nenhum módulo da TUI importa este módulo.
"""

import logging
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, Engine, text

from ytmusic_tui.library.errors import (
    BackupFailedError,
    LibraryError,
    MigrationFailedError,
    SchemaIncompatibleError,
    translate_db_error,
)
from ytmusic_tui.library.models import Base
from ytmusic_tui.permissions import secure_directory, secure_file

logger = logging.getLogger(__name__)

#: Subdiretório dos backups, ao lado do ``library.db`` (nunca o mesmo arquivo).
BACKUP_DIR_NAME = "backups"

#: Quantos backups manter (mais recentes); o recém-criado nunca é podado.
BACKUP_KEEP = 5

_VERSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at DATETIME NOT NULL
)
"""


@dataclass(frozen=True)
class MigrationStep:
    """Um passo de migração; ``apply`` roda dentro de uma transação."""

    version: int
    description: str
    apply: Callable[[Connection], None]


def _migration_1_sync_tables(connection: Connection) -> None:
    """Cria tabelas ausentes do esquema atual em banco legado.

    Caso concreto: ``download_tasks`` (T04) em bancos criados antes dela.
    ``create_all`` só cria o que falta (checkfirst), então o passo também
    cobre qualquer tabela nova futura que chegue sem migração própria.
    """
    Base.metadata.create_all(connection)


def _migration_2_add_is_missing(connection: Connection) -> None:
    """Adiciona ``tracks.is_missing`` — "registro sem arquivo" (Q8/T05).

    O texto da coluna é idêntico ao que o SQLAlchemy emite no esquema atual
    (``is_missing BOOLEAN DEFAULT 0 NOT NULL``, no fim das colunas —
    exatamente onde o ``ADD COLUMN`` a insere); o SQLite só não preserva a
    quebra de linha do CREATE original, então a equivalência de DDL
    novo-vs-migrado é comparada com normalização de espaços (teste). O
    ``DEFAULT 0`` também preenche as linhas existentes, requisito de uma
    coluna NOT NULL adicionada a tabela com dados.
    """
    connection.exec_driver_sql(
        "ALTER TABLE tracks ADD COLUMN is_missing BOOLEAN DEFAULT 0 NOT NULL"
    )


#: Passos, em ordem — a versão corrente é a do último.
MIGRATIONS: tuple[MigrationStep, ...] = (
    MigrationStep(
        1,
        "cria tabelas ausentes do esquema atual (ex.: download_tasks)",
        _migration_1_sync_tables,
    ),
    MigrationStep(
        2,
        "adiciona tracks.is_missing (arquivo ausente na reconciliação — Q8)",
        _migration_2_add_is_missing,
    ),
)

#: Versão corrente do esquema (nunca escrever à mão: sai da última migração).
SCHEMA_VERSION = MIGRATIONS[-1].version


@dataclass(frozen=True)
class MigrationOutcome:
    """Resumo do que a abertura do banco fez (log e testes)."""

    created: bool
    from_version: int
    to_version: int
    applied: tuple[int, ...]
    backup_path: Path | None


def migrate(
    engine: Engine,
    *,
    db_path: Path | None = None,
    backup_dir: Path | None = None,
    keep_backups: int = BACKUP_KEEP,
    migrations: Sequence[MigrationStep] = MIGRATIONS,
    now: datetime | None = None,
) -> MigrationOutcome:
    """Leva o banco à versão do código, com backup antes de qualquer DDL.

    ``db_path``/``backup_dir``/``migrations``/``now`` são injetáveis para
    testes (tmp e passos controlados); os padrões usam o caminho do engine,
    ``<dir do banco>/backups`` e o relógio corrente.
    """
    path = db_path if db_path is not None else _engine_db_path(engine)
    reference = now if now is not None else datetime.now(UTC)
    # Alvo = última migração fornecida (na prática, SCHEMA_VERSION; listas
    # injetadas em teste definem o próprio alvo).
    target = migrations[-1].version if migrations else SCHEMA_VERSION
    version, tables = _inspect(engine, path)

    if version is None and not tables:
        return _create_fresh(engine, path, reference, target)
    if version is None:
        if "tracks" not in tables:
            raise SchemaIncompatibleError(
                f"{path or 'banco'} não parece ser o banco do ytmusic-tui "
                "(sem a tabela 'tracks' e sem controle de versão); nada foi alterado"
            )
        version = 0  # legado T01–T04: reconhecido pelo esquema
    if version > SCHEMA_VERSION:
        raise SchemaIncompatibleError(
            f"esquema v{version} é mais novo que o app (v{SCHEMA_VERSION}); "
            "atualize o ytmusic-tui — nada foi alterado"
        )

    pending = [step for step in migrations if step.version > version]
    if not pending:
        return MigrationOutcome(
            created=False,
            from_version=version,
            to_version=version,
            applied=(),
            backup_path=None,
        )

    backup = _backup(engine, path, backup_dir, version, target, reference)
    applied = _apply_pending(engine, pending, backup, reference)
    _prune_backups(backup.parent, path, keep_backups, current=backup)
    return MigrationOutcome(
        created=False,
        from_version=version,
        to_version=target,
        applied=tuple(applied),
        backup_path=backup,
    )


def read_schema_version(engine: Engine, db_path: Path | None = None) -> int | None:
    """Versão persistida (maior), ou ``None`` se o controle não existe.

    Insumo de diagnóstico (T13); falhas viram erros tipados.
    """
    path = db_path if db_path is not None else _engine_db_path(engine)
    try:
        with engine.connect() as connection:
            if "schema_migrations" not in _table_names(connection):
                return None
            return _max_version(connection)
    except Exception as error:
        translated = translate_db_error(error, path)
        if translated is not None:
            raise translated from error
        raise


def _inspect(engine: Engine, path: Path | None) -> tuple[int | None, set[str]]:
    """Lê (versão persistida, tabelas) numa conexão só; falhas tipadas."""
    try:
        with engine.connect() as connection:
            tables = _table_names(connection)
            version = _max_version(connection) if "schema_migrations" in tables else None
    except Exception as error:
        translated = translate_db_error(error, path)
        if translated is not None:
            raise translated from error
        raise
    return version, tables


def _create_fresh(
    engine: Engine, path: Path | None, reference: datetime, target: int
) -> MigrationOutcome:
    """Banco novo: esquema atual + estampo da versão, numa única transação."""
    try:
        with _transaction(engine) as connection:
            Base.metadata.create_all(connection)
            _ensure_version_table(connection)
            _stamp(connection, target, "esquema inicial (create_all)", reference)
    except Exception as error:
        translated = translate_db_error(error, path)
        if translated is not None:
            raise translated from error
        raise
    logger.info("Banco novo criado no esquema atual v%s: %s", target, path)
    return MigrationOutcome(
        created=True,
        from_version=0,
        to_version=target,
        applied=(),
        backup_path=None,
    )


@contextmanager
def _transaction(engine: Engine) -> Iterator[Connection]:
    """Transação de verdade para DDL/DML das migrações.

    O driver pysqlite em modo legado só abre transação para DML — DDL
    ficaria em autocommit e o rollback de uma migração falha não desfaria
    nada (comprovado por teste de falha injetada). Aqui o BEGIN/COMMIT/
    ROLLBACK são emitidos por nós numa conexão AUTOCOMMIT; a mudança fica
    **contida nas migrações** (o engine global segue com o comportamento
    normal de transações, testado sob concorrência).
    """
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("BEGIN")
        try:
            yield connection
        except BaseException:
            connection.exec_driver_sql("ROLLBACK")
            raise
        connection.exec_driver_sql("COMMIT")


def _apply_pending(
    engine: Engine,
    pending: Sequence[MigrationStep],
    backup_path: Path,
    reference: datetime,
) -> list[int]:
    """Aplica os passos pendentes, um por transação (falha → rollback total)."""
    applied: list[int] = []
    for step in pending:
        try:
            with _transaction(engine) as connection:
                _ensure_version_table(connection)
                step.apply(connection)
                _stamp(connection, step.version, step.description, reference)
        except Exception as error:
            raise MigrationFailedError(
                f"migração v{step.version} falhou e foi revertida "
                f"(dados intactos; backup pré-migração em {backup_path})"
            ) from error
        applied.append(step.version)
        logger.info("Esquema migrado para v%s: %s", step.version, step.description)
    return applied


def _backup(
    engine: Engine,
    db_path: Path | None,
    backup_dir: Path | None,
    from_version: int,
    to_version: int,
    reference: datetime,
) -> Path:
    """``VACUUM INTO`` antes de qualquer DDL; falha → ``BackupFailedError``."""
    directory = backup_dir
    if directory is None:
        if db_path is None:
            raise BackupFailedError(
                "caminho do banco desconhecido; migração abortada, dados intactos"
            )
        directory = db_path.parent / BACKUP_DIR_NAME
    try:
        # §8.3/T06: pasta de backups é dado privado (0700; só aperta existente).
        secure_directory(directory, label="diretório de backups")
        stem = db_path.stem if db_path is not None else "library"
        target = _unique_backup_path(directory, stem, from_version, to_version, reference)
        _vacuum_into(engine, target, db_path)
        # O arquivo do backup também nasce com o modo do umask — aperta.
        secure_file(target, label="backup da biblioteca")
    except LibraryError:
        raise
    except Exception as error:
        raise BackupFailedError(
            f"backup falhou ({error}); migração abortada, dados intactos"
        ) from error
    logger.info("Backup pré-migração criado: %s", target)
    return target


def _vacuum_into(engine: Engine, target: Path, db_path: Path | None) -> None:
    """Cópia consistente via ``VACUUM INTO``, fora de transação (autocommit).

    ``VACUUM`` não roda dentro de transação: usa a conexão crua do pool com
    ``isolation_level = None`` (comportamento restaurado em seguida). Nunca
    é ``cp`` de arquivo em uso.
    """
    connection = engine.raw_connection()
    try:
        dbapi = connection.driver_connection
        if dbapi is None:  # pragma: no cover — SQLite sempre expõe a conexão crua
            raise RuntimeError("conexão DBAPI indisponível para o backup")
        isolation = dbapi.isolation_level
        dbapi.isolation_level = None
        try:
            cursor = dbapi.cursor()
            try:
                cursor.execute("VACUUM INTO ?", (str(target),))
            finally:
                cursor.close()
        finally:
            dbapi.isolation_level = isolation
    except sqlite3.DatabaseError as error:
        translated = translate_db_error(error, db_path)
        if translated is not None:
            raise translated from error
        raise
    finally:
        connection.close()


def _unique_backup_path(
    directory: Path, stem: str, from_version: int, to_version: int, reference: datetime
) -> Path:
    """``<stem>-AAAAMMDD-HHMMSS-v<de>-v<para>.db``, sem colisão."""
    stamp = reference.strftime("%Y%m%d-%H%M%S")
    base = f"{stem}-{stamp}-v{from_version}-v{to_version}"
    target = directory / f"{base}.db"
    counter = 1
    while target.exists():
        target = directory / f"{base}-{counter}.db"
        counter += 1
    return target


def _prune_backups(directory: Path, db_path: Path | None, keep: int, current: Path) -> None:
    """Mantém os ``keep`` mais recentes (+ o ``current``); poda nunca fatal.

    Só entram na poda arquivos do padrão próprio (``<stem>-*.db``), na
    própria pasta de backups; o recém-criado nunca é removido e falha de
    remoção fica no log.
    """
    if keep < 0 or not directory.is_dir():
        return
    stem = db_path.stem if db_path is not None else "library"
    try:
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.name.startswith(f"{stem}-") and path.suffix == ".db"
        ]
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        logger.warning("Falha ao listar backups em %s (poda ignorada)", directory, exc_info=True)
        return
    for path in candidates[keep:]:
        if path == current:
            continue  # o backup recém-criado nunca entra na poda
        try:
            path.unlink()
        except OSError:
            logger.warning("Falha ao podar backup antigo %s (ignorada)", path, exc_info=True)
        else:
            logger.info("Backup antigo podado: %s", path)


def _table_names(connection: Connection) -> set[str]:
    """Nomes das tabelas do banco (insumo da detecção de estado)."""
    rows = connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).scalars()
    return {str(name) for name in rows}


def _max_version(connection: Connection) -> int | None:
    """Maior versão estampada (a tabela existir é responsabilidade do chamador)."""
    value = connection.execute(text("SELECT MAX(version) FROM schema_migrations")).scalar()
    return int(value) if value is not None else None


def _ensure_version_table(connection: Connection) -> None:
    connection.execute(text(_VERSION_TABLE_DDL))


def _stamp(connection: Connection, version: int, description: str, reference: datetime) -> None:
    connection.execute(
        text(
            "INSERT INTO schema_migrations (version, description, applied_at) "
            "VALUES (:version, :description, :applied_at)"
        ),
        {
            "version": version,
            "description": description,
            "applied_at": reference.isoformat(" ", timespec="seconds"),
        },
    )


def _engine_db_path(engine: Engine) -> Path | None:
    """Caminho do arquivo do engine SQLite (``None`` em bancos de memória)."""
    database = engine.url.database
    return Path(database) if database else None
