"""Logging da aplicação em arquivo.

A TUI ocupa o terminal inteiro: qualquer log escrito em stderr sujaria a
tela. Por isso o pacote ``ytmusic_tui`` grava tudo em um arquivo no
diretório de logs do sistema (``platformdirs``), com rotação para não
crescer sem limite.
"""

import logging
from io import TextIOWrapper
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_dir

from ytmusic_tui.permissions import secure_directory, secure_file

_PACKAGE = "ytmusic-tui"
_LOG_FILE_NAME = "ytmusic-tui.log"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """Rotação que mantém o log e as rotações em 0600 (§8.3/T06).

    ``_open`` cobre tanto a criação inicial quanto a reabertura feita pelo
    ``doRollover``. O ajuste NÃO é logado (``log_tightening=False``): a
    rotação roda com o lock do handler preso — registrar ali travaria o
    processo (deadlock).
    """

    def _open(self) -> TextIOWrapper:
        stream = super()._open()
        secure_file(Path(self.baseFilename), label="arquivo de log", log_tightening=False)
        return stream


def log_file_path() -> Path:
    """Caminho do arquivo de log (existindo ou não)."""
    return Path(user_log_dir(_PACKAGE)) / _LOG_FILE_NAME


def setup_logging(level: int = logging.INFO) -> Path:
    """Configura o logger do pacote para gravar em arquivo.

    Idempotente (chamadas repetidas não duplicam handlers) e devolve o
    caminho do arquivo, útil para diagnóstico.
    """
    path = log_file_path()
    # §8.3/T06: diretório de log 0700 (existente só aperta).
    secure_directory(path.parent, label="diretório de log")

    logger = logging.getLogger("ytmusic_tui")
    logger.setLevel(level)
    if not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        handler = _PrivateRotatingFileHandler(
            path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
    return path
