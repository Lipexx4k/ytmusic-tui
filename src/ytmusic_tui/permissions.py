"""Permissões privadas para os dados da aplicação (§8.3/T06).

Regra do projeto:

- **Criação estrita**: diretórios internos nascem 0700 e arquivos 0600 com
  ``chmod`` DEPOIS da criação — o modo efetivo não pode depender do umask do
  processo (funciona em qualquer ambiente, inclusive com ``umask 0``).
- **Existente só aperta**: nunca adicionamos permissão a algo que já existe
  (se o usuário restringiu mais que o padrão, respeitamos); quando o modo
  está mais frouxo, removemos SÓ os bits de grupo/outros e registramos no log.
- **``download_dir`` é mídia do usuário**: nunca é chmodado; só as pastas de
  trabalho (``.tmp``/``.quarantine``) e os dados da aplicação recebem modo
  privado.
- **Nunca precisa de root**: nenhum caminho de sistema é tocado.

``log_tightening=False`` existe para o handler de log: registrar de dentro do
``doRollover`` (com o lock do logging preso) travaria o processo.
"""

import logging
import os
import stat
from pathlib import Path

from ytmusic_tui.errors import ConfigError

__all__ = ["DIR_MODE", "FILE_MODE", "secure_directory", "secure_file", "tighten_mode"]

logger = logging.getLogger(__name__)

#: Modo dos diretórios internos (aplicação e pastas de trabalho).
DIR_MODE = 0o700
#: Modo dos arquivos internos (banco, backups, log, configuração).
FILE_MODE = 0o600


def tighten_mode(mode: int) -> int:
    """Remove os bits de grupo/outros de ``mode`` (nunca adiciona permissão)."""
    return mode & ~0o077


def secure_directory(path: Path, *, label: str = "diretório") -> None:
    """Garante ``path`` como diretório privado (0700), sem afrouxar o existente.

    Cria com ``mkdir(parents=True)`` e aplica ``chmod(0700)`` — umask-agnóstico.
    Se já existir, apenas remove bits de grupo/outros (apertar), com log.
    Falha de criação/permissão vira ``ConfigError`` com mensagem clara.
    """
    created = False
    try:
        path.mkdir(parents=True, exist_ok=False)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise ConfigError(f"não foi possível criar o {label} {path}: {exc}") from exc

    if not path.is_dir():
        raise ConfigError(f"o {label} {path} existe, mas não é um diretório")

    if created:
        _apply_mode(path, DIR_MODE, label=label)
        return

    try:
        current = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise ConfigError(f"não foi possível inspecionar o {label} {path}: {exc}") from exc
    if tighten_mode(current) != current:
        _apply_mode(path, tighten_mode(current), label=label, log_tightening=True)


def secure_file(path: Path, *, label: str = "arquivo", log_tightening: bool = True) -> None:
    """Aperta (nunca afrouxa) um ARQUIVO existente para no máximo 0600.

    Arquivos nascem de bibliotecas (SQLite, logging, ``VACUUM INTO``): não há
    "criação" nossa para forçar antes — o ajuste é sempre pós-criação. Remove
    SÓ os bits de grupo/outros; um arquivo já mais restrito (ex.: 0400) fica
    como está. Arquivo ausente é no-op (quem cria chama de novo).
    """
    try:
        current = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("Não foi possível inspecionar %s: %s", label, path, exc_info=True)
        return
    if tighten_mode(current) != current:
        _apply_mode(path, tighten_mode(current), label=label, log_tightening=log_tightening)


def _apply_mode(path: Path, mode: int, *, label: str, log_tightening: bool = False) -> None:
    """Aplica ``mode``; falha de chmod vira aviso (FS sem modos POSIX)."""
    try:
        os.chmod(path, mode)
    except OSError:
        logger.warning("Não foi possível ajustar o modo do %s: %s", label, path, exc_info=True)
        return
    if log_tightening:
        logger.info("Permissões apertadas para %04o no %s: %s", mode, label, path)
