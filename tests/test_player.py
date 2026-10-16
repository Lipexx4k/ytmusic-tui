"""Testes para o player mpv (lógica sem depender de rede/áudio)."""

import locale
import logging
import shutil
import sys

import pytest

from ytmusic_tui.player import MPVPlayer, PlayerState, TrackInfo

# `ytmusic_tui/__init__.py` exporta a instância `player`, que sombreia o
# atributo de módulo. O módulo real fica em sys.modules.
player_mod = sys.modules["ytmusic_tui.player"]


class _FakeMpv:
    """Substituto de mpv.MPV sem libmpv."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.played: str | None = None

    def property_observer(self, name):
        def wrapper(fn):
            return fn

        return wrapper

    def event_callback(self, *event_types):
        def wrapper(fn):
            return fn

        return wrapper

    def play(self, url):
        self.played = url

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


# ===== Lifecycle explícito do mpv (T06-R3 · §8.2) =====


def test_start_is_idempotent_and_shutdown_allows_restart(monkeypatch):
    """R3: start idempotente; shutdown encerra e um novo start recria."""
    created: list[_FakeMpv] = []

    class _TrackedMpv(_FakeMpv):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.terminated = 0
            created.append(self)

        def terminate(self):
            self.terminated += 1

    monkeypatch.setattr(player_mod.mpv, "MPV", _TrackedMpv)
    monkeypatch.setattr(player_mod.settings, "mpv_volume", 42)
    monkeypatch.setattr(player_mod.settings, "mpv_audio_quality", "high")

    p = MPVPlayer()
    assert p.start() is True
    first = p._mpv
    assert p.start() is True  # idempotente: não cria segundo handle
    assert p._mpv is first
    assert len(created) == 1

    p.shutdown()
    assert p._mpv is None
    assert first is not None and first.terminated == 1
    p.shutdown()  # idempotente também
    assert first.terminated == 1

    assert p.start() is True  # reinício permitido após shutdown
    assert len(created) == 2
    assert p._mpv is not first
    p.shutdown()
    assert created[1].terminated == 1


@pytest.mark.parametrize("error", [OSError("libmpv ausente"), RuntimeError("init recusado")])
def test_start_failure_becomes_error_state_without_raising(monkeypatch, error):
    """Falha ao criar o handle vira ERROR + evento, nunca exceção na TUI."""

    class _Explode:
        def __init__(self, **kwargs):
            raise error

    monkeypatch.setattr(player_mod.mpv, "MPV", _Explode)
    monkeypatch.setattr(player_mod.settings, "mpv_volume", 42)
    monkeypatch.setattr(player_mod.settings, "mpv_audio_quality", "high")

    p = MPVPlayer()
    events: list[tuple[str, str]] = []
    p.on_event(lambda e: events.append((e.event, e.data.get("message", ""))))

    assert p.start() is False
    assert p._mpv is None
    assert p.state is PlayerState.ERROR
    assert any(name == "error" and "mpv indisponível" in msg for name, msg in events)


def test_play_starts_on_demand_and_tracks_source_url(monkeypatch):
    """play() inicia o handle sob demanda (compatível com o fluxo antigo)."""
    monkeypatch.setattr(player_mod.mpv, "MPV", _FakeMpv)
    monkeypatch.setattr(player_mod.settings, "mpv_volume", 42)
    monkeypatch.setattr(player_mod.settings, "mpv_audio_quality", "high")

    p = MPVPlayer()
    info = TrackInfo(video_id="v", title="T", source_url="http://servidor/a.mp3")

    assert p.play(info) is True
    assert p._mpv is not None and p._mpv.played == "http://servidor/a.mp3"


def test_play_with_broken_mpv_returns_false_without_raising(monkeypatch):
    """Handle quebrado: play() devolve False e a UI recebe evento de erro."""

    class _Explode:
        def __init__(self, **kwargs):
            raise OSError("sem libmpv")

    monkeypatch.setattr(player_mod.mpv, "MPV", _Explode)
    monkeypatch.setattr(player_mod.settings, "mpv_volume", 42)
    monkeypatch.setattr(player_mod.settings, "mpv_audio_quality", "high")

    p = MPVPlayer()
    events: list[str] = []
    p.on_event(lambda e: events.append(e.event))
    info = TrackInfo(video_id="v", title="T", source_url="http://servidor/a.mp3")

    assert p.play(info) is False
    assert p.state is PlayerState.ERROR
    assert "error" in events


def test_numeric_locale_is_restored_before_every_handle(monkeypatch):
    """LC_NUMERIC=C é definido ANTES de CADA criação do handle (R3)."""
    calls: list[tuple] = []

    class _TrackedMpv(_FakeMpv):
        def __init__(self, **kwargs):
            calls.append(("mpv",))
            super().__init__(**kwargs)

    real_setlocale = locale.setlocale

    def tracked_setlocale(category, value=None):
        calls.append(("setlocale", category, value))
        return real_setlocale(category, value)

    monkeypatch.setattr(player_mod.mpv, "MPV", _TrackedMpv)
    monkeypatch.setattr(player_mod.locale, "setlocale", tracked_setlocale)
    monkeypatch.setattr(player_mod.settings, "mpv_volume", 42)
    monkeypatch.setattr(player_mod.settings, "mpv_audio_quality", "high")

    p = MPVPlayer()
    p.start()
    p.shutdown()
    p.start()
    p.shutdown()

    assert calls == [
        ("setlocale", locale.LC_NUMERIC, "C"),
        ("mpv",),
        ("setlocale", locale.LC_NUMERIC, "C"),
        ("mpv",),
    ]


def test_missing_yt_dlp_warns_once_and_keeps_hook_default(monkeypatch, caplog):
    """Extra aprovado no T06: aviso ÚNICO quando o yt-dlp não existe."""
    monkeypatch.setattr(player_mod.MPVPlayer, "_find_yt_dlp", staticmethod(lambda: None))
    monkeypatch.setattr(player_mod.mpv, "MPV", _FakeMpv)
    monkeypatch.setattr(player_mod.settings, "mpv_volume", 42)
    monkeypatch.setattr(player_mod.settings, "mpv_audio_quality", "high")

    p = MPVPlayer()
    with caplog.at_level(logging.WARNING, logger="ytmusic_tui.player"):
        p.start()
        p.shutdown()
        p.start()
        p.shutdown()

    assert p._mpv is None  # encerrado ao final do teste
    avisos = [r for r in caplog.records if "yt-dlp" in r.getMessage()]
    assert len(avisos) == 1

    p2 = MPVPlayer()
    p2.start()
    assert "script_opts" not in p2._mpv.kwargs
    p2.shutdown()


def test_yt_dlp_path_is_passed_to_the_hook(monkeypatch):
    """Com yt-dlp localizado, o hook do mpv usa o binário do ambiente."""
    monkeypatch.setattr(
        player_mod.MPVPlayer, "_find_yt_dlp", staticmethod(lambda: "/opt/venv/yt-dlp")
    )
    monkeypatch.setattr(player_mod.mpv, "MPV", _FakeMpv)
    monkeypatch.setattr(player_mod.settings, "mpv_volume", 42)
    monkeypatch.setattr(player_mod.settings, "mpv_audio_quality", "high")

    p = MPVPlayer()
    p.start()

    assert p._mpv is not None
    assert p._mpv.kwargs["script_opts"] == "ytdl_hook-ytdl_path=/opt/venv/yt-dlp"
    p.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
