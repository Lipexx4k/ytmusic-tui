"""Dobraduras (fakes) da suíte de segurança — nunca tocam rede nem dados reais.

``FakeYoutubeDL`` reproduz o ciclo mínimo do yt-dlp usado pelo gerenciador:
"baixa" para o template do temporário da reserva, "converte" e dispara os
``post_hooks`` com o caminho final. As opções reais chegam intactas em
``self.opts`` — o contrato (limites, silêncio) é testável sem rede.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import ytmusic_tui.download as download_mod


class FakeDownloadError(Exception):
    """Espelha ``yt_dlp.utils.DownloadError`` para o isinstance do worker."""


class FakeUtils:
    DownloadError = FakeDownloadError


class FakeYoutubeDL:
    """yt-dlp falso: baixa, "converte" e chama os hooks de verdade."""

    def __init__(self, opts: dict):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def download(self, urls: list[str]) -> None:
        template = self.opts["outtmpl"]
        final = Path(template.replace("%(ext)s", "mp3"))
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"audio-convertido-mp3")
        for hook in self.opts.get("post_hooks", []):
            hook(str(final))


def fake_yt_dlp(youtube_dl_cls: type = FakeYoutubeDL) -> SimpleNamespace:
    """Módulo ``yt_dlp`` falso em torno de uma classe ``YoutubeDL``."""
    return SimpleNamespace(utils=FakeUtils, YoutubeDL=youtube_dl_cls)


def install_settings(monkeypatch: pytest.MonkeyPatch, download_dir: Path) -> None:
    """Substitui ``download_mod.settings`` por um namespace isolado."""
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
