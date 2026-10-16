"""Logging da aplicação em arquivo, em JSON Lines (§13.1/T13).

A TUI ocupa o terminal inteiro: qualquer log escrito em stderr sujaria a
tela. Por isso o pacote ``ytmusic_tui`` grava tudo em um arquivo no
diretório de logs do sistema (``platformdirs``), com rotação para não
crescer sem limite (1 MB × 3 rotações — máximo 4 MB).

Cada linha é um objeto JSON com campos fixos: ``ts`` (ISO-8601 com offset
local), ``level``, ``component`` (logger sem o prefixo ``ytmusic_tui.``),
``operation_id``, ``event``, ``error_code``, ``message`` e — só quando há
``exc_info`` — ``detail`` (traceback). Registro comum tem ``event=null``;
evento estruturado vem de :func:`log_event`.

Privacidade (§13.2/T13): o formatter aplica ``mask_diagnostics`` (HOME →
``~``, URLs sem query/credencial) e ``mask_secrets`` (cabeçalhos de
credencial → ``[REDACTED]``) em mensagem e traceback — quem chama não
precisa lembrar de mascarar, e credencial não persiste no disco.
"""

import json
import logging
from datetime import datetime
from io import TextIOWrapper
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_dir

from ytmusic_tui.diagnostics import mask_diagnostics, mask_secrets
from ytmusic_tui.permissions import secure_directory, secure_file

__all__ = ["log_event", "log_file_path", "setup_logging"]

_PACKAGE = "ytmusic-tui"
_LOG_FILE_NAME = "ytmusic-tui.log"
#: Prefixo do pacote: o que sobra dele vira o campo ``component``.
_PACKAGE_PREFIX = "ytmusic_tui."
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3


def _mask(text: str) -> str:
    """Mascaramento de privacidade aplicado a mensagem e traceback (§13.2)."""
    return mask_secrets(mask_diagnostics(text))


class _JsonFormatter(logging.Formatter):
    """Um objeto JSON por registro, com privacidade aplicada (§13.1)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created).astimezone().isoformat(),
            "level": record.levelname,
            "component": record.name.removeprefix(_PACKAGE_PREFIX),
            "operation_id": getattr(record, "operation_id", None),
            "event": getattr(record, "event", None),
            "error_code": getattr(record, "error_code", None),
            "message": _mask(record.getMessage()),
        }
        if record.exc_info:
            payload["detail"] = _mask(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


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


def log_event(
    component: str,
    event: str,
    message: str,
    *,
    operation_id: str | None = None,
    error_code: str | None = None,
    level: int = logging.INFO,
    exc_info: bool = False,
) -> None:
    """Registra um evento estruturado (§13.1/T13).

    ``component`` vira ``ytmusic_tui.<component>`` (ex.: ``"download"``);
    os campos extras viajam em ``extra=`` e viram campos do JSON. A
    mensagem não precisa vir mascarada — o formatter garante a privacidade
    de todo registro (§13.2).
    """
    logging.getLogger(f"{_PACKAGE_PREFIX}{component}").log(
        level,
        message,
        extra={
            "event": event,
            "operation_id": operation_id,
            "error_code": error_code,
        },
        exc_info=exc_info,
    )


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
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
    return path
