"""Testes das migrações versionadas, backup e integridade (§7/T05-R1/R2/R5).

Padrões de segurança destes testes: sempre em tmp (nunca o banco real),
cobrindo banco novo, legado T01–T04, esquema mais novo, arquivo alheio,
falha de backup, rollback de migração, restauração comprovada e retenção.
"""

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from ytmusic_tui.library import migrations
from ytmusic_tui.library.database import DatabaseManager
from ytmusic_tui.library.errors import (
    BackupFailedError,
    DatabaseCorruptError,
    DatabasePermissionError,
    MigrationFailedError,
    SchemaIncompatibleError,
)


def _table_names(path: Path) -> set[str]:
    """Tabelas do arquivo (sqlite3 cru, sem SQLAlchemy)."""
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {str(row[0]) for row in rows}
    finally:
        connection.close()


def _schema_dump(path: Path) -> list[tuple[str, str, str]]:
    """DDL de todos os objetos, ordenado — insumo da equivalência."""
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
        )
        return [(str(kind), str(name), str(sql)) for kind, name, sql in rows]
    finally:
        connection.close()


def _make_legacy_db(path: Path) -> None:
    """Banco no esquema T01–T04: tabelas atuais, sem download_tasks, com dados.

    Sem ``schema_migrations`` (o mecanismo nasce na T05) — é exatamente o
    que um banco real do usuário criado antes desta tarefa parece.
    """
    manager = DatabaseManager(path)
    manager.create_all()
    with manager.engine.begin() as connection:
        connection.execute(text("DROP TABLE download_tasks"))
        connection.execute(
            text(
                "INSERT INTO artists (source_id, name, source) "
                "VALUES ('art1', 'Artista', 'youtube_music')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO tracks (source_id, title, source) "
                "VALUES ('vid1', 'Faixa', 'youtube_music')"
            )
        )
    manager.close()


def test_fresh_db_is_created_stamped_at_current_version(tmp_path):
    """Banco novo nasce no esquema atual, estampado — nunca migra do zero."""
    db = tmp_path / "library.db"
    manager = DatabaseManager(db)
    outcome = manager.migrate()

    assert outcome.created is True
    assert outcome.from_version == 0
    assert outcome.to_version == migrations.SCHEMA_VERSION
    assert outcome.applied == ()
    assert outcome.backup_path is None
    assert manager.schema_version() == migrations.SCHEMA_VERSION
    assert not (tmp_path / migrations.BACKUP_DIR_NAME).exists()  # nada a copiar
    manager.close()

    # Segunda abertura é no-op: não recria nem re-estampa.
    manager = DatabaseManager(db)
    again = manager.migrate()
    assert again.created is False
    assert again.applied == ()
    assert manager.schema_version() == migrations.SCHEMA_VERSION
    manager.close()


def test_legacy_db_migrates_preserving_data_and_matching_fresh_ddl(tmp_path):
    """Legado T01–T04: reconhecido pelo esquema, backup antes do DDL, migra."""
    db = tmp_path / "library.db"
    _make_legacy_db(db)

    manager = DatabaseManager(db)
    outcome = manager.migrate()

    assert outcome.created is False
    assert outcome.from_version == 0
    assert outcome.to_version == migrations.SCHEMA_VERSION
    assert outcome.applied == (1,)
    assert outcome.backup_path is not None and outcome.backup_path.is_file()
    assert manager.schema_version() == migrations.SCHEMA_VERSION

    # O backup foi tirado ANTES de qualquer DDL: estado pré-migração.
    assert "download_tasks" not in _table_names(outcome.backup_path)
    # A migração aplicou o passo: tabela nova criada e dados preservados.
    assert "download_tasks" in _table_names(db)
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artists").fetchone()[0] == 1
        assert connection.execute("SELECT title FROM tracks").fetchone()[0] == "Faixa"

    # Equivalência de DDL: banco novo vs. banco migrado são idênticos.
    fresh = tmp_path / "fresh.db"
    fresh_manager = DatabaseManager(fresh)
    fresh_manager.migrate()
    fresh_manager.close()
    assert _schema_dump(db) == _schema_dump(fresh)
    manager.close()


def test_too_new_schema_raises_typed_and_touches_nothing(tmp_path):
    """Esquema de versão futura → erro tipado, zero alterações."""
    db = tmp_path / "library.db"
    manager = DatabaseManager(db)
    manager.migrate()
    with manager.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO schema_migrations (version, description, applied_at) "
                "VALUES (:version, 'futuro', '2030-01-01 00:00:00')"
            ),
            {"version": migrations.SCHEMA_VERSION + 1},
        )
    before = _schema_dump(db)

    with pytest.raises(SchemaIncompatibleError):
        manager.migrate()

    assert _schema_dump(db) == before
    assert not (tmp_path / migrations.BACKUP_DIR_NAME).exists()
    manager.close()


def test_foreign_sqlite_file_raises_typed_without_changes(tmp_path):
    """Arquivo SQLite que não é o banco do app → erro tipado, nada alterado."""
    db = tmp_path / "library.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE outra (x INTEGER)")
    connection.execute("INSERT INTO outra VALUES (1)")
    connection.commit()
    connection.close()
    before = _schema_dump(db)

    manager = DatabaseManager(db)
    with pytest.raises(SchemaIncompatibleError):
        manager.migrate()

    assert _schema_dump(db) == before
    assert "download_tasks" not in _table_names(db)
    manager.close()


def test_backup_failure_aborts_before_any_ddl(tmp_path, monkeypatch):
    """Backup falhou → migração aborta com erro tipado e o banco não muda."""
    db = tmp_path / "library.db"
    _make_legacy_db(db)
    manager = DatabaseManager(db)

    def _fail(*args, **kwargs):
        raise OSError("disco cheio")

    monkeypatch.setattr(migrations, "_vacuum_into", _fail)
    with pytest.raises(BackupFailedError):
        manager.migrate()

    # Nada mudou: sem versão, sem download_tasks, dados intactos.
    assert "schema_migrations" not in _table_names(db)
    assert "download_tasks" not in _table_names(db)
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 1
    manager.close()


def test_backup_restores_original_state_and_can_migrate_again(tmp_path):
    """Restauração comprovada: o backup abre, tem os dados e migra de novo."""
    db = tmp_path / "library.db"
    _make_legacy_db(db)

    manager = DatabaseManager(db)
    outcome = manager.migrate()
    backup = outcome.backup_path
    assert backup is not None

    # O backup é um banco completo do estado anterior.
    assert "download_tasks" not in _table_names(backup)
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT title FROM tracks").fetchone()[0] == "Faixa"

    # Drill de desastre: o banco é substituído pelo backup e volta a migrar.
    manager.close()
    db.write_bytes(backup.read_bytes())
    manager = DatabaseManager(db)
    second = manager.migrate()
    assert second.created is False
    assert second.applied == (1,)
    assert manager.schema_version() == migrations.SCHEMA_VERSION
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 1
    manager.close()


def test_failed_migration_rolls_back_and_keeps_backup(tmp_path):
    """Falha no meio de um passo → rollback completo (sem DDL parcial)."""
    db = tmp_path / "library.db"
    _make_legacy_db(db)

    def _boom(connection):
        connection.execute(text("CREATE TABLE lixo (x INTEGER)"))
        raise RuntimeError("falha injetada no meio do passo")

    bad_step = (migrations.MigrationStep(1, "passo que falha", _boom),)
    manager = DatabaseManager(db)
    with pytest.raises(MigrationFailedError):
        migrations.migrate(manager.engine, db_path=db, migrations=bad_step)

    assert "lixo" not in _table_names(db)
    assert "schema_migrations" not in _table_names(db)  # nada estampado
    assert "download_tasks" not in _table_names(db)
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 1
    backups = list((tmp_path / migrations.BACKUP_DIR_NAME).glob("*.db"))
    assert len(backups) == 1  # backup pré-migração preservado
    manager.close()


def test_backup_retention_keeps_newest_and_current(tmp_path):
    """Retenção: mantém os 5 mais recentes do padrão próprio + o atual."""
    db = tmp_path / "library.db"
    backup_dir = tmp_path / migrations.BACKUP_DIR_NAME
    backup_dir.mkdir()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(7):
        fake = backup_dir / f"library-20260101-00000{index}-v0-v1.db"
        fake.write_bytes(b"backup falso")
        mtime = (base + timedelta(hours=index)).timestamp()
        os.utime(fake, (mtime, mtime))
    foreign = backup_dir / "anotacoes.txt"
    foreign.write_text("não é backup do app")

    _make_legacy_db(db)
    manager = DatabaseManager(db)
    outcome = manager.migrate()  # cria o atual e poda

    assert foreign.exists()  # arquivo alheio nunca é tocado
    assert outcome.backup_path is not None and outcome.backup_path.is_file()
    kept = sorted(path.name for path in backup_dir.glob("library-*.db"))
    assert len(kept) == migrations.BACKUP_KEEP
    assert outcome.backup_path.name in kept
    # Fica o atual + os 4 falsos mais recentes; os 3 mais antigos são podados.
    assert "library-20260101-000000-v0-v1.db" not in kept
    assert "library-20260101-000002-v0-v1.db" not in kept
    assert "library-20260101-000003-v0-v1.db" in kept
    assert "library-20260101-000006-v0-v1.db" in kept
    manager.close()


def test_prune_never_deletes_current_even_with_keep_zero(tmp_path):
    """A poda nunca remove o backup recém-criado, qualquer que seja o keep."""
    backup_dir = tmp_path / migrations.BACKUP_DIR_NAME
    backup_dir.mkdir()
    current = backup_dir / "library-20260101-000000-v0-v1.db"
    older = backup_dir / "library-20250101-000000-v0-v1.db"
    current.write_bytes(b"atual")
    older.write_bytes(b"antigo")

    migrations._prune_backups(backup_dir, tmp_path / "library.db", 0, current=current)

    assert current.exists()
    assert not older.exists()


def test_corrupt_db_raises_typed_error(tmp_path):
    """Arquivo que não é SQLite: erro tipado no migrate e em qualquer query."""
    db = tmp_path / "library.db"
    db.write_bytes(b"isto nao e um banco sqlite " * 200)

    manager = DatabaseManager(db)
    with pytest.raises(DatabaseCorruptError):
        manager.migrate()
    with pytest.raises(DatabaseCorruptError), manager.session() as session:
        session.execute(text("SELECT name FROM sqlite_master"))
    manager.close()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora permissões de arquivo")
def test_unreadable_db_raises_permission_error(tmp_path):
    """Arquivo sem permissão de leitura → erro tipado de permissão."""
    db = tmp_path / "library.db"
    manager = DatabaseManager(db)
    manager.migrate()
    manager.close()

    db.chmod(0o000)
    try:
        with pytest.raises(DatabasePermissionError):
            DatabaseManager(db).migrate()
    finally:
        db.chmod(0o644)


def test_integrity_check_ok_on_healthy_db(tmp_path):
    """R5: banco saudável → relatório ok."""
    db = tmp_path / "library.db"
    manager = DatabaseManager(db)
    manager.migrate()

    report = manager.integrity_check()
    assert report.ok is True
    assert report.messages == ("ok",)
    assert report.db_path == db
    manager.close()


def test_integrity_check_raises_typed_on_unreadable_file(tmp_path):
    """R5: corrupção que impede a leitura vira erro tipado (não relatório)."""
    db = tmp_path / "library.db"
    db.write_bytes(b"x" * 4096)

    manager = DatabaseManager(db)
    with pytest.raises(DatabaseCorruptError):
        manager.integrity_check()
    manager.close()


def test_schema_version_is_none_without_version_table(tmp_path):
    """Banco só com create_all (tabelas, sem versionamento) não tem versão."""
    db = tmp_path / "library.db"
    manager = DatabaseManager(db)
    manager.create_all()
    assert manager.schema_version() is None
    manager.close()
