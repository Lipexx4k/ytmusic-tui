"""Cache persistente das respostas da API (T10-R4).

Camada best-effort, em disco, para as duas leituras que dominam a latência:
``search_catalog`` (TTL 5 min) e ``get_album`` (TTL 24h). Grava o PAYLOAD
dos modelos internos (T10-R1), nunca a resposta crua: o arquivo não tem URL
de stream nem dado que a UI não consuma (há teste varrendo o conteúdo por
``watch?v=``/``googlevideo``).

Formato: envelope versionado (``{"version", "cached_at", "payload"}``) em
JSON; versão diferente ou JSON corrompido = cache miss. Escrita atômica
(tmp + ``os.replace``) sob ``threading.Lock`` — as duas requisições
paralelas da busca escrevem concorrentemente sem se atropelar.

Teto total (20 MiB): ao passar, os arquivos mais antigos (mtime) são
podados, preservando o mais recente. O diretório ``cache_dir/api`` nasce
0700 (A4); qualquer falha de disco é só um ``warning`` — o app nunca
quebra porque o cache falhou.
"""

import contextlib
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ytmusic_tui.errors import ConfigError
from ytmusic_tui.permissions import secure_directory

__all__ = [
    "ENVELOPE_VERSION",
    "MAX_CACHE_BYTES",
    "TTL_ALBUM_S",
    "TTL_SEARCH_S",
    "ResponseCache",
    "cache_key",
]

logger = logging.getLogger("ytmusic_tui.api.cache")

#: TTL por escopo (Q-C): busca muda rápido; álbum quase nunca.
TTL_SEARCH_S = 300.0
TTL_ALBUM_S = 86400.0

#: Teto total do cache em disco (Q-C).
MAX_CACHE_BYTES = 20 * 1024 * 1024

#: Versão do envelope: subir quando o formato do payload mudar.
ENVELOPE_VERSION = 1


def cache_key(*parts: object) -> str:
    """Chave estável (SHA-256 truncada) para os argumentos da consulta."""
    raw = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class ResponseCache:
    """Cache JSON em disco com envelope versionado, TTL por escopo e teto."""

    def __init__(
        self,
        root: Path,
        *,
        ttl_search: float = TTL_SEARCH_S,
        ttl_album: float = TTL_ALBUM_S,
        max_bytes: int = MAX_CACHE_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = root
        self._ttl = {"search": ttl_search, "album": ttl_album}
        self._max_bytes = max_bytes
        self._clock = clock
        self._lock = threading.Lock()

    # ===== leitura =====

    def get(self, scope: str, key: str) -> Any | None:
        """Payload válido (versão certa, dentro do TTL) ou ``None``."""
        path = self._path(scope, key)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("cache ignorado (%s): %s", path, exc)
            return None

        try:
            envelope = json.loads(raw)
            version = envelope["version"]
            cached_at = float(envelope["cached_at"])
            payload = envelope["payload"]
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("cache corrompido removido (%s): %s", path, exc)
            self._discard(path)
            return None

        if version != ENVELOPE_VERSION:
            logger.debug("cache de versão antiga ignorado (%s)", path)
            return None

        age = self._clock() - cached_at
        if age > self._ttl_for(scope):
            logger.debug("cache expirado (%s, %.0fs)", path, age)
            self._discard(path)
            return None

        return payload

    # ===== escrita =====

    def put(self, scope: str, key: str, payload: Any) -> None:
        """Grava o payload de forma atômica (best-effort: nunca levanta)."""
        path = self._path(scope, key)
        try:
            data = json.dumps(
                {
                    "version": ENVELOPE_VERSION,
                    "cached_at": self._clock(),
                    "payload": payload,
                },
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("payload não serializável não foi cacheado: %s", exc)
            return

        with self._lock:
            try:
                # 0700 estrito no diretório do cache (A4); FileExistsError de
                # diretório já existente é só apertar.
                secure_directory(self._root, label="cache da API")
                fd, tmp_name = tempfile.mkstemp(dir=self._root, prefix=".tmp-", suffix=".json")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        handle.write(data)
                    os.replace(tmp_name, path)
                except BaseException:
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_name)
                    raise
                self._prune_locked()
            except (OSError, ConfigError) as exc:
                logger.warning("cache não gravado (%s): %s", path, exc)

    # ===== internos =====

    def _ttl_for(self, scope: str) -> float:
        return self._ttl.get(scope, 0.0)

    def _path(self, scope: str, key: str) -> Path:
        return self._root / f"{scope}-{key}.json"

    def _discard(self, path: Path) -> None:
        with contextlib.suppress(OSError):
            path.unlink()

    def _prune_locked(self) -> None:
        """Remove os mais antigos (mtime) até caber no teto; poupa o último."""
        try:
            entries: list[tuple[float, int, Path]] = []
            for path in self._root.glob("*.json"):
                stat = path.stat()
                entries.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            return

        total = sum(size for _mtime, size, _path in entries)
        if total <= self._max_bytes or len(entries) < 2:
            return

        entries.sort(key=lambda entry: entry[0])  # mais antigo primeiro
        for _mtime, size, path in entries[:-1]:  # o mais recente nunca sai
            if total <= self._max_bytes:
                break
            with contextlib.suppress(OSError):
                path.unlink()
                total -= size
