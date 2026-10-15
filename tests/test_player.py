"""Testes para o player mpv (lógica sem depender de rede/áudio)."""
import locale
import shutil
import sys

import pytest

from ytmusic_tui.player import MPVPlayer

# `ytmusic_tui/__init__.py` exporta a instância `player`, que sombreia o
# atributo de módulo. O módulo real fica em sys.modules.
player_mod = sys.modules["ytmusic_tui.player"]


class _FakeMpv:
    """Substituto de mpv.MPV sem libmpv."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def property_observer(self, name):
        def wrapper(fn):
            return fn

        return wrapper

    def event_callback(self, *event_types):
        def wrapper(fn):
            return fn

        return wrapper

    def terminate(self):
        pass


def test_find_yt_dlp_prefers_venv_sibling(monkeypatch, tmp_path):
    """Deve priorizar o yt-dlp do ambiente (venv) sobre binários do sistema.

    Um yt-dlp antigo do sistema (ex.: /usr/bin/yt-dlp, versão 2025.x) é
    rejeitado pelo YouTube; a versão gerida pelo pip é a que funciona.
    """
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake = venv_bin / "yt-dlp"
    fake.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
    fake.chmod(0o755)

    monkeypatch.setattr(sys, "executable", str(venv_bin / "python"))
    monkeypatch.setattr(shutil, "which", lambda *a, **k: "/usr/bin/yt-dlp")

    assert MPVPlayer._find_yt_dlp() == str(fake)


def test_find_yt_dlp_falls_back_to_path(monkeypatch):
    """Sem yt-dlp no ambiente, usa o que existir no PATH."""
    monkeypatch.setattr(sys, "executable", "/tmp/venv-inexistente/bin/python")
    monkeypatch.setattr(shutil, "which", lambda *a, **k: "/usr/bin/yt-dlp")

    assert MPVPlayer._find_yt_dlp() == "/usr/bin/yt-dlp"


def test_find_yt_dlp_none(monkeypatch):
    """Sem yt-dlp em lugar nenhum, retorna None (mpv usa o hook embutido)."""
    monkeypatch.setattr(sys, "executable", "/tmp/venv-inexistente/bin/python")
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)

    assert MPVPlayer._find_yt_dlp() is None


def test_ensure_mpv_started_restores_numeric_locale(monkeypatch, tmp_path):
    """O libmpv exige LC_NUMERIC='C'; o ytmusicapi muda o locale para en_US.

    Regressão: sem restaurar o LC_NUMERIC, criar o handle do mpv após uma
    busca (ytmusicapi) abortava o processo com segfault.
    """
    monkeypatch.setattr(player_mod.mpv, "MPV", _FakeMpv)
    monkeypatch.setattr(player_mod.settings, "mpv_volume", 42)

    try:
        original = locale.setlocale(locale.LC_NUMERIC, None)
        locale.setlocale(locale.LC_NUMERIC, "en_US.UTF-8")
    except locale.Error as exc:  # pragma: no cover - ambiente sem o locale
        pytest.skip(f"locale en_US.UTF-8 indisponível: {exc}")

    p = MPVPlayer()
    try:
        p._ensure_mpv_started()

        assert p._mpv is not None
        assert locale.setlocale(locale.LC_NUMERIC, None) == "C"
    finally:
        locale.setlocale(locale.LC_NUMERIC, original)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])