"""Falsos da camada L2 (T08 · §10) — autossuficientes, sem rede nem host.

Adaptam o contrato já provado em ``tests/security/_fakes.py`` (escreve no
``outtmpl`` da reserva, dispara os hooks de verdade), sem importar de lá: as
camadas não ficam acopladas. A diferença central: o "ffmpeg" aqui é um
**script executável real** encontrado pelo PATH (``shutil.which``) e
executado por subprocess pelo stub — nenhum seam interno é substituído.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import ytmusic_tui.download as download_mod

#: Script do "ffmpeg" falso (T08): registra a execução num arquivo-marcador
#: (prova de que o processo rodou de verdade) e simula ok/fail/slow por
#: variável de ambiente. Nunca toca em áudio de verdade.
FFMPEG_SCRIPT = """#!/bin/sh
mode="${FAKE_FFMPEG_MODE:-ok}"
if [ -n "$FAKE_FFMPEG_MARKER" ]; then
    printf '%s %s\\n' "$mode" "$*" >> "$FAKE_FFMPEG_MARKER"
fi
if [ "$mode" = "slow" ]; then
    sleep "${FAKE_FFMPEG_SLEEP:-0.25}"
fi
if [ "$mode" = "fail" ]; then
    printf 'ffmpeg: falha simulada (exit 1)\\n' >&2
    exit 1
fi
# Uso do stub: ffmpeg -i ENTRADA SAIDA — o "encode" copia os bytes.
if [ -n "$2" ] && [ -n "$3" ]; then
    cp "$2" "$3"
fi
exit 0
"""


class FakeDownloadError(Exception):
    """Espelha ``yt_dlp.utils.DownloadError`` para o isinstance do worker."""


class FakeUtils:
    DownloadError = FakeDownloadError


def install_fake_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Binário falso de verdade: script +x no PATH + arquivo-marcador.

    O marcador registra modo e argv a cada execução — nenhum mock de
    ``subprocess`` está envolvido; quem "converte" é o processo do script.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "ffmpeg"
    script.write_text(FFMPEG_SCRIPT, encoding="utf-8")
    script.chmod(0o755)
    marker = tmp_path / "ffmpeg.marker"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_FFMPEG_MARKER", str(marker))
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "ok")
    return SimpleNamespace(bin_dir=bin_dir, script=script, marker=marker)


def install_settings(monkeypatch: pytest.MonkeyPatch, download_dir: Path) -> None:
    """Substitui ``download_mod.settings`` por um namespace isolado (L2)."""
    monkeypatch.setattr(
        download_mod,
        "settings",
        SimpleNamespace(
            download_dir=download_dir,
            download_format="mp3",
            download_quality="320",
            embed_metadata=True,
            download_concurrent=1,
        ),
    )


class StubYoutubeDL:
    """yt-dlp falso com os modos da matriz §10.1 — hooks e ffmpeg de verdade.

    Ordem: progresso "downloading" → escreve o intermediário no template da
    reserva → executa o ffmpeg falso (subprocess, do PATH) → progresso
    "finished" (ponto onde o abort é observado, T02-R3) → ``post_hooks`` com
    o caminho convertido. Os hooks são os REAIS do gerenciador — o fake não
    cancela nada por conta própria.
    """

    def __init__(self, opts: dict[str, Any], mode: str = "ok") -> None:
        self.opts = opts
        self.mode = mode

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _progress(self, data: dict[str, Any]) -> None:
        for hook in self.opts.get("progress_hooks", []):
            hook(data)

    def _post(self, path: Path) -> None:
        for hook in self.opts.get("post_hooks", []):
            hook(str(path))

    def download(self, urls: list[str]) -> None:
        if self.mode == "extract-error":
            raise FakeDownloadError("ERROR: [youtube] abc123: Sign in to confirm you're not a bot")

        template = self.opts["outtmpl"]
        source = Path(template.replace("%(ext)s", "webm"))
        output = Path(template.replace("%(ext)s", "mp3"))
        source.parent.mkdir(parents=True, exist_ok=True)
        self._progress({"status": "downloading", "_percent_str": "50.0%"})
        source.write_bytes(b"audio-intermediario-webm")

        if self.mode == "enospc":
            # ENOSPC REAL do kernel (/dev/full); o yt-dlp real embrulharia o
            # OSError num DownloadError — é o que fazemos aqui.
            try:
                with open("/dev/full", "wb") as full:
                    full.write(b"x" * 4096)
            except OSError as e:
                raise FakeDownloadError(f"unable to write data: {e}") from e
            raise FakeDownloadError("unable to write data: /dev/full aceitou escrita")

        if self.mode in ("missing", "empty"):
            # Fidelidade da infraestrutura (rotulado como tal, sem cobertura
            # nova): "sem saída" × "saída vazia" chegam distinguíveis ao fluxo
            # real de validação/publicação.
            if self.mode == "empty":
                output.write_bytes(b"")
            self._progress({"status": "finished"})
            self._post(output)
            return

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:  # pragma: no cover — o pré-check falha antes
            raise FakeDownloadError("ffmpeg não encontrado (PATH)")
        proc = subprocess.run(
            [ffmpeg, "-i", str(source), str(output)],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise FakeDownloadError(f"Postprocessing: ffmpeg falhou (exit {proc.returncode})")
        self._progress({"status": "finished"})
        self._post(output)


def fake_yt_dlp(mode: str = "ok") -> SimpleNamespace:
    """Módulo ``yt_dlp`` falso em torno do stub."""

    class _YoutubeDL(StubYoutubeDL):
        def __init__(self, opts: dict[str, Any]) -> None:
            super().__init__(opts, mode=mode)

    return SimpleNamespace(utils=FakeUtils, YoutubeDL=_YoutubeDL)


def install_yt_dlp(monkeypatch: pytest.MonkeyPatch, mode: str = "ok") -> None:
    """Aponta o import tardio (``_load_yt_dlp``) para o stub."""
    monkeypatch.setattr(download_mod, "_load_yt_dlp", lambda: fake_yt_dlp(mode))
