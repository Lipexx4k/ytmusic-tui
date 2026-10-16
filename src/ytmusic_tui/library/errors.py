"""Erros tipados da biblioteca local (T05-R4).

Casos distintos pedem mensagens e ações distintas: banco vazio é normal (a
UI mostra a biblioteca vazia), enquanto inacessível, sem permissão, esquema
incompatível e corrompido são falhas com causas próprias — a camada TUI
decide pelo **tipo**, nunca por string.

``translate_db_error`` centraliza a leitura das exceções do sqlite3,
inclusive as embrulhadas pelo SQLAlchemy (que preservam a original em
``.orig``): nenhum outro módulo precisa conhecer sqlite3 para classificar.
Restrições (``IntegrityError``) não são traduzidas — são do domínio.
"""

import os
import sqlite3
from pathlib import Path

__all__ = [
    "BackupFailedError",
    "DatabaseCorruptError",
    "DatabaseInaccessibleError",
    "DatabasePermissionError",
    "LibraryError",
    "MigrationFailedError",
    "SchemaIncompatibleError",
    "translate_db_error",
]


class LibraryError(Exception):
    """Erro da biblioteca local (base); a UI mapeia o tipo para a mensagem."""


class DatabaseInaccessibleError(LibraryError):
    """O banco existe mas não pôde ser aberto/lido/gravado agora."""


class DatabasePermissionError(DatabaseInaccessibleError):
    """Falta permissão do sistema de arquivos (no banco ou no diretório)."""


class DatabaseCorruptError(LibraryError):
    """O arquivo não é um banco SQLite válido ou está corrompido."""


class SchemaIncompatibleError(LibraryError):
    """Esquema mais novo que o app, ou arquivo que não é o banco do app."""


class BackupFailedError(LibraryError):
    """O backup pré-migração falhou; a migração foi abortada (dados intactos)."""


class MigrationFailedError(LibraryError):
    """Uma migração falhou e foi revertida (rollback); o backup fica mantido."""


#: Trechos (casefold) que denunciam arquivo corrompido/estranho no sqlite3.
_CORRUPT_HINTS = ("file is not a database", "malformed", "corrupt")


def translate_db_error(error: BaseException, db_path: Path | None = None) -> LibraryError | None:
    """Traduz um erro do sqlite3 (ou embrulhado pelo SQLAlchemy) num tipado.

    Devolve ``None`` quando o erro não é do arquivo em si — o chamador
    re-levanta o original (ex.: violação de restrição é do domínio).
    """
    source = getattr(error, "orig", error)
    if isinstance(source, sqlite3.IntegrityError):
        return None
    if not isinstance(source, sqlite3.DatabaseError):
        return None

    message = str(source)
    lowered = message.casefold()
    if any(hint in lowered for hint in _CORRUPT_HINTS):
        return DatabaseCorruptError(
            f"o arquivo não é um banco válido ou está corrompido ({message})"
        )
    if isinstance(source, sqlite3.OperationalError):
        return _classify_operational_error(lowered, db_path)
    return None


def _classify_operational_error(lowered: str, db_path: Path | None) -> LibraryError:
    """Classifica ``OperationalError`` (a maior parte das falhas de acesso)."""
    if "unable to open database file" in lowered:
        return _classify_open_failure(db_path)
    if "locked" in lowered:
        return DatabaseInaccessibleError("o banco está em uso (lock); tente novamente em instantes")
    return DatabaseInaccessibleError(f"falha de acesso ao banco ({lowered})")


def _classify_open_failure(db_path: Path | None) -> LibraryError:
    """Distingue permissão de inacessibilidade no "unable to open"."""
    if db_path is None:
        return DatabaseInaccessibleError("não foi possível abrir o banco")
    if db_path.exists():
        if not os.access(db_path, os.R_OK | os.W_OK):
            return DatabasePermissionError(f"sem permissão de leitura/escrita em {db_path}")
        return DatabaseInaccessibleError(f"não foi possível abrir {db_path} (arquivo em uso?)")
    parent = db_path.parent
    if not parent.exists():
        return DatabaseInaccessibleError(f"o diretório do banco não existe: {parent}")
    if not os.access(parent, os.W_OK):
        return DatabasePermissionError(f"sem permissão de escrita em {parent}")
    return DatabaseInaccessibleError(f"não foi possível criar {db_path}")
