"""L2 do player (T11-R2): teardown auditável com libmpv REAL.

Sem skip: o CI instala ``mpv``/``libmpv-dev`` e a máquina do autor tem a
biblioteca (padrão do T08). Nada de rede e nada de áudio de verdade: o
``yt-dlp`` do hook é um script falso executável (mesmo padrão do ffmpeg
falso do T08) que grava o próprio PID e dorme — o teste observa o processo
vivo → morto no ``shutdown()`` (INV-8: nada de órfão/zumbi pendurado) e que
eventos atrasados do handle morto não alcançam callbacks registrados.

O singleton do player é global da suíte; a fixture ``real_player`` o
devolve limpo no teardown (``shutdown`` + remoção dos callbacks registrados
no teste).
"""

from __future__ import annotations

import contextlib
import os
import signal
import time
from pathlib import Path

import pytest

from ytmusic_tui.player import TrackInfo, player
from ytmusic_tui.tui.app import YTMusicTUI

#: Script do "yt-dlp" falso (R2): registra o próprio PID e dorme — tempo de
#: sobra para o teste flagrar o processo vivo e derrubar o player.
FAKE_YTDLP_SCRIPT = """#!/bin/sh
printf '%s\\n' "$$" > "$FAKE_YTDLP_PID_FILE"
sleep 300
"""


@pytest.fixture
def real_player():
    """Singleton do player com libmpv REAL, isolado por teste.

    O teardown garante ``shutdown()`` (nenhum handle fica vivo entre testes)
    e remove callbacks registrados AQUI — a lista global não acumula sonda
    de teste (T11-R2: nada de callback morto chamado).
    """
    instance = player
    before = list(instance._callbacks)
    try:
        yield instance
    finally:
        instance.shutdown()
        for callback in list(instance._callbacks):
            if callback not in before:
                instance.remove_callback(callback)


def _pid_state(pid: int) -> str | None:
    """Estado em ``/proc``: ``None`` se sumiu; ``Z`` = morto sem ser reapado."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return stat.rsplit(")", 1)[1].split()[0]


def _wait_for_file(path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return
        time.sleep(0.05)
    pytest.fail(f"{path.name} não apareceu a tempo (o fake yt-dlp não rodou)")


def test_shutdown_reaps_the_ytdl_hook_child(real_player, monkeypatch, tmp_path):
    """T11-R2/INV-8: PID vivo durante a carga → morto depois do ``shutdown()``.

    O fake yt-dlp grava o PID e dorme; depois do shutdown o processo tem de
    sumir do ``/proc`` dentro do timeout — vivo OU zumbi falha. A prova é
    com libmpv REAL: é o ``terminate()`` do mpv que derruba e reapa o filho
    do hook no destroy.
    """
    fake = tmp_path / "yt-dlp"
    fake.write_text(FAKE_YTDLP_SCRIPT, encoding="utf-8")
    fake.chmod(0o755)
    pid_file = tmp_path / "ytdl.pid"
    monkeypatch.setenv("FAKE_YTDLP_PID_FILE", str(pid_file))
    monkeypatch.setattr(real_player, "_find_yt_dlp", lambda: str(fake))

    assert real_player.start() is True
    assert real_player.play(
        TrackInfo(video_id="FAKE", source_url="https://www.youtube.com/watch?v=FAKE")
    )

    _wait_for_file(pid_file, timeout=10)
    pid = int(pid_file.read_text().strip())
    assert _pid_state(pid) is not None  # vivo: o hook está executando o fake

    try:
        real_player.shutdown()

        deadline = time.monotonic() + 5
        state = _pid_state(pid)
        while state is not None and time.monotonic() < deadline:
            time.sleep(0.05)
            state = _pid_state(pid)
        assert state is None, f"filho do ytdl_hook não morreu no shutdown (state={state})"
    finally:
        # Nunca deixar órfão pendurado no CI mesmo se a asserção falhar.
        if _pid_state(pid) is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


def test_real_handle_teardown_drops_events_without_crash(real_player, tmp_path):
    """T11-R2: com handle real, nada é entregue depois do ``shutdown()``.

    Uma carga que falha rápido (arquivo local inexistente, hermético) gera
    eventos reais do handle antes do teardown; depois do shutdown, eventos
    da API (``next_track``) são descartados pela guarda e a thread de
    eventos já foi junta — nada chega ao callback.
    """
    events: list[str] = []
    real_player.on_event(lambda e: events.append(e.event))
    assert real_player.start() is True
    assert real_player.play(TrackInfo(video_id="X", source_url=str(tmp_path / "nao-existe.mp3")))

    deadline = time.monotonic() + 5
    while not events and time.monotonic() < deadline:
        time.sleep(0.05)
    assert events, "mpv real não emitiu nenhum evento antes do teardown"

    real_player.shutdown()
    assert real_player._mpv is None
    settled = len(events)

    # Evento da API depois do shutdown: descartado pela guarda (T11-R2).
    real_player.next_track()
    time.sleep(0.3)  # janela para eventos atrasados do handle morto (se houvesse)

    assert len(events) == settled


@pytest.mark.asyncio
async def test_app_teardown_with_real_handle_does_not_crash(real_player):
    """T11-R2: ``run_test`` com handle real — encerrar o app não quebra.

    O guard C0 (pilha de telas vazia) e a guarda de eventos cobrem a janela
    entre o fechamento das telas e o ``shutdown`` do player; a barra recebe
    um evento real (``next``) antes do teardown.
    """
    app = YTMusicTUI()
    async with app.run_test():
        assert real_player.start() is True
        real_player.next_track()  # player → callback do app → tela (sem fila)

    # run_test saiu: o unmount removeu o callback e encerrou o handle real.
    assert real_player._mpv is None
    assert app._on_player_event not in real_player._callbacks
