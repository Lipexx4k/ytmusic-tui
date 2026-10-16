"""Testes unitários da tradução de erros do sqlite3 (T05-R4).

A classificação por tipo é o que permite a UI mostrar a mensagem certa;
aqui garantimos que cada exceção cai no balde correto (e que violação de
restrição continua sendo erro do domínio, sem tradução) e que
``describe_library_error`` dá uma mensagem própria por caso.
"""

import os
import sqlite3
from pathlib import Path

import pytest

from ytmusic_tui.library.errors import (
    AudioFileMissingError,
    BackupFailedError,
    DatabaseCorruptError,
    DatabaseInaccessibleError,
    DatabasePermissionError,
    LibraryError,
    MigrationFailedError,
    SchemaIncompatibleError,
    describe_library_error,
    translate_db_error,
)


def test_locked_database_is_inaccessible():
    translated = translate_db_error(
        sqlite3.OperationalError("database is locked"), Path("/tmp/library.db")
    )
    assert isinstance(translated, DatabaseInaccessibleError)
    assert not isinstance(translated, DatabasePermissionError)


def test_corrupt_file_is_corrupt_error():
    translated = translate_db_error(sqlite3.DatabaseError("file is not a database"))
    assert isinstance(translated, DatabaseCorruptError)


def test_integrity_error_is_domain_not_translated():
    assert translate_db_error(sqlite3.IntegrityError("UNIQUE constraint failed")) is None


def test_unrelated_exception_is_not_translated():
    assert translate_db_error(ValueError("boom")) is None


def test_missing_parent_directory_is_inaccessible(tmp_path):
    translated = translate_db_error(
        sqlite3.OperationalError("unable to open database file"),
        tmp_path / "sem" / "library.db",
    )
    assert isinstance(translated, DatabaseInaccessibleError)
    assert not isinstance(translated, DatabasePermissionError)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora permissões de arquivo")
def test_unwritable_directory_is_permission(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        translated = translate_db_error(
            sqlite3.OperationalError("unable to open database file"),
            blocked / "library.db",
        )
    finally:
        blocked.chmod(0o700)
    assert isinstance(translated, DatabasePermissionError)


def test_sqlalchemy_wrapped_error_uses_orig(tmp_path):
    """Erros embrulhados pelo SQLAlchemy (``.orig``) também são traduzidos."""
    from sqlalchemy.exc import OperationalError as SAOperationalError

    wrapped = SAOperationalError("SELECT 1", {}, sqlite3.OperationalError("database is locked"))
    translated = translate_db_error(wrapped, tmp_path / "library.db")
    assert isinstance(translated, DatabaseInaccessibleError)


def test_describe_library_error_gives_specific_message_per_type():
    """Cada tipo tem mensagem/ação próprias — subclasse vence a base (R4)."""
    cases: list[tuple[LibraryError, str]] = [
        (DatabasePermissionError("sem permissão de leitura/escrita em /x"), "permissão"),
        (DatabaseCorruptError("não é um banco válido"), "backup"),
        (SchemaIncompatibleError("esquema v999 é mais novo que o app"), "compatível"),
        (BackupFailedError("backup falhou (disk full)"), "backup"),
        (MigrationFailedError("migração v2 falhou e foi revertida"), "revertida"),
        (AudioFileMissingError("arquivo não encontrado: /m/sumiu.mp3"), "Ctrl+D"),
        (DatabaseInaccessibleError("o banco está em uso (lock)"), "tente de novo"),
    ]

    messages = []
    for error, keyword in cases:
        message = describe_library_error(error)
        assert keyword in message, (type(error).__name__, keyword)
        assert str(error) in message  # o detalhe original continua visível
        messages.append(message)

    # Um caso, uma mensagem: nada de texto genérico repetido.
    assert len(set(messages)) == len(cases)
    # A subclasse de permissão não cai na mensagem da base.
    assert "tente de novo" not in describe_library_error(DatabasePermissionError("x"))


def test_describe_library_error_falls_back_to_str_for_unknown_type():
    """Erro tipado sem mapeamento não esconde a mensagem original."""
    assert describe_library_error(LibraryError("erro qualquer")) == "erro qualquer"
