"""Mascaramento de diagnóstico na UI (§8.3/§8.4 · T06).

Checklist coberta aqui:

- ``mask_home``/``mask_urls`` (funções puras): HOME vira ``~``; URL perde
  query, fragment e credenciais; texto comum passa intacto;
- ``_set_failed`` é o ponto ÚNICO em que ``task.error`` recebe texto de
  terceiro — a tabela de downloads e o toast de falha leem daí, então já
  nascem mascarados (teste de ponta a ponta na TUI em ``test_tui.py``);
- ``describe_library_error`` (toasts e estado "biblioteca indisponível")
  mascara o detalhe do erro tipado;
- eventos de **erro** do player mascaram a mensagem, mas eventos de faixa
  NUNCA são tocados (dado do usuário não é diagnóstico).
"""

import sys
from pathlib import Path

from ytmusic_tui.diagnostics import mask_diagnostics, mask_home, mask_urls
from ytmusic_tui.download import DownloadManager, DownloadStatus, DownloadTask
from ytmusic_tui.library.errors import DatabaseInaccessibleError, describe_library_error
from ytmusic_tui.player import MPVPlayer

player_mod = sys.modules["ytmusic_tui.player"]

HOME = str(Path.home())
SIGNED_URL = "https://rr1---sn-xyz.googlevideo.com/videoplayback?expire=1&sig=SEGREDO123&x=2"


def test_mask_home_replaces_home_only():
    """HOME literal vira ``~``; resto do texto fica igual."""
    assert mask_home(f"falha em {HOME}/Music/f.mp3") == "falha em ~/Music/f.mp3"
    assert mask_home("sem nada sensível") == "sem nada sensível"


def test_mask_urls_strips_query_fragment_and_credentials():
    """URL assinada perde token; userinfo (usuário:senha) some."""
    masked = mask_urls(f"erro em {SIGNED_URL}")
    assert "SEGREDO123" not in masked
    assert "sig=" not in masked
    assert "googlevideo.com/videoplayback" in masked
    assert masked.endswith("?…")  # marca que havia parâmetros

    with_userinfo = mask_urls("http://usuario:senha@exemplo.com/video.mp4#trecho")
    assert "senha" not in with_userinfo
    assert with_userinfo == "http://exemplo.com/video.mp4?…"


def test_mask_urls_keeps_clean_url_and_trailing_punctuation():
    """URL sem query passa intacta; pontuação do texto não é engolida."""
    assert mask_urls("veja https://music.youtube.com/watch") == (
        "veja https://music.youtube.com/watch"
    )
    assert mask_urls("falhou (https://a.example/v, tente de novo)") == (
        "falhou (https://a.example/v, tente de novo)"
    )


def test_mask_diagnostics_combines_both():
    """O texto final não tem HOME nem token, mas mantém o contexto útil."""
    masked = mask_diagnostics(f"erro: {HOME}/dl.mp3 {SIGNED_URL}")
    assert HOME not in masked
    assert "SEGREDO123" not in masked
    assert "~/dl.mp3" in masked


def test_set_failed_masks_download_errors():
    """Ponto único dos erros de download: ``task.error`` nasce mascarado."""
    task = DownloadTask(video_id="v", title="T")
    task.transition_to(DownloadStatus.RUNNING)

    DownloadManager._set_failed(task, f"403 em {HOME}/Music/f.mp3 ({SIGNED_URL})")

    assert task.status is DownloadStatus.FAILED
    assert task.error is not None
    assert HOME not in task.error
    assert "SEGREDO123" not in task.error


def test_describe_library_error_masks_detail():
    """O detalhe do erro tipado (caminho/URL) chega mascarado ao toast."""
    error = DatabaseInaccessibleError(
        f"não foi possível abrir {HOME}/.local/share/library.db ({SIGNED_URL})"
    )
    described = describe_library_error(error)

    assert HOME not in described
    assert "SEGREDO123" not in described
    assert "~/.local/share/library.db" in described


def test_player_error_event_is_masked_but_track_data_is_not(monkeypatch):
    """Erro do mpv sai mascarado; eventos de faixa/posição passam intactos."""
    monkeypatch.setattr(player_mod.settings, "mpv_volume", 30)
    player = MPVPlayer()
    seen: list = []
    player.on_event(seen.append)

    player._emit("error", {"message": f"falha ao abrir {SIGNED_URL} em {HOME}"})
    player._emit("track_changed", {"title": f"{HOME}/não mascarar isto"})

    error_message = seen[0].data["message"]
    assert "SEGREDO123" not in error_message
    assert HOME not in error_message
    assert "googlevideo.com" in error_message  # contexto continua legível
    assert seen[1].data["title"] == f"{HOME}/não mascarar isto"
