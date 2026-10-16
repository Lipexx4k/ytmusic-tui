"""Downloads na camada L2 (T08 · §10.1): worker real, ffmpeg EXECUTÁVEL.

Nada de seam interno de ffmpeg: o binário falso é um script real no PATH e
o stub do yt-dlp o executa por subprocess — como o yt-dlp de verdade faz
com os pós-processadores. Casos cobertos: sucesso, falha de conversão,
ausência total de ffmpeg (PATH real), conversão lenta + cancelamento do
usuário (observado no progress_hook real), extração com erro e ENOSPC real
do kernel (/dev/full).
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import ytmusic_tui.download as download_mod
from tests.integration_local._fakes import (
    FakeDownloadError,
    FakeUtils,
    install_fake_ffmpeg,
)
from ytmusic_tui.download import DownloadStatus
from ytmusic_tui.download.store import DownloadTaskStore
from ytmusic_tui.player import TrackInfo
from ytmusic_tui.tui.app import YTMusicTUI


def _queue(env, video_id: str):
    return env.manager.queue_download(video_id=video_id, title="T", artist="A", album="Alb")


def _temp_empty(env) -> bool:
    temp_dir = env.download_dir / ".tmp"
    return not temp_dir.exists() or list(temp_dir.iterdir()) == []


async def test_download_completes_with_real_fake_ffmpeg(tmp_path, monkeypatch, make_l2_env):
    """Sucesso ponta a ponta: o ffmpeg falso EXECUTA e o fluxo publica."""
    fake = install_fake_ffmpeg(tmp_path, monkeypatch)
    env = make_l2_env(mode="ok")

    result = await env.manager.download(_queue(env, "vid-ok"))

    assert result.status is DownloadStatus.COMPLETED
    final = result.file_path
    assert final is not None and final.exists()
    # O "encode" do script (cp) alimentou a publicação com os bytes reais:
    assert final.read_bytes() == b"audio-intermediario-webm"
    # Prova de execução de verdade: marcador com modo e argv do processo.
    assert fake.marker.exists()
    assert fake.marker.read_text().startswith("ok -i ")
    # Reserva liberada: nem lock, nem temporário.
    assert _temp_empty(env)


async def test_ffmpeg_failure_marks_failed_and_publishes_nothing(
    tmp_path, monkeypatch, make_l2_env
):
    """exit ≠ 0 no ffmpeg (processo real) → FAILED, nada publicado."""
    fake = install_fake_ffmpeg(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "fail")
    env = make_l2_env(mode="ok")

    result = await env.manager.download(_queue(env, "vid-fail"))

    assert result.status is DownloadStatus.FAILED
    assert "ffmpeg" in (result.error or "")
    assert fake.marker.read_text().startswith("fail -i ")  # o script rodou mesmo
    assert not list(env.download_dir.rglob("*.mp3"))
    assert _temp_empty(env)


async def test_ffmpeg_absent_shows_clear_message_before_reserving(
    tmp_path, monkeypatch, make_l2_env
):
    """Sem ffmpeg no PATH (seam real, sem monkeypatch): mensagem clara §10.1.

    O yt-dlp é o de verdade (instalado) — o import-check passa e a checagem
    de ffmpeg falha pelo ``shutil.which`` do PATH controlado.
    """
    empty = tmp_path / "sem-ffmpeg"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    env = make_l2_env(mode=None)

    result = await env.manager.download(_queue(env, "vid-sem-ffmpeg"))

    assert result.status is DownloadStatus.FAILED
    assert "ffmpeg não encontrado no PATH" in (result.error or "")
    # Falhou ANTES de reservar: nem pasta de trabalho, nem arquivo, nem lock.
    assert not (env.download_dir / ".tmp").exists()
    assert not list(env.download_dir.rglob("*.mp3"))


async def test_cancel_during_slow_conversion_is_immediate_and_publishes_nothing(
    tmp_path, monkeypatch, make_l2_env
):
    """Cancelar durante a conversão lenta: imediato e sem publicar.

    O abort é observado no progress_hook REAL (T02-R3): o script do ffmpeg
    roda de verdade (modo slow) e é o stub que dispara os hooks — nunca o
    fake cancela por conta própria.
    """
    fake = install_fake_ffmpeg(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "slow")
    monkeypatch.setenv("FAKE_FFMPEG_SLEEP", "0.4")
    env = make_l2_env(mode="ok")

    task = _queue(env, "vid-cancel")
    pending = asyncio.create_task(env.manager.download(task))

    deadline = time.monotonic() + 5
    while not fake.marker.exists():  # marcador = script executando (sleep)
        assert time.monotonic() < deadline, "o ffmpeg falso não chegou a executar"
        await asyncio.sleep(0.01)

    assert env.manager.cancel_download("vid-cancel") is True
    assert task.status is DownloadStatus.CANCELLED  # imediato: não bloqueia

    result = await asyncio.wait_for(pending, timeout=5)
    assert result.status is DownloadStatus.CANCELLED
    # Nada publicado; temporário (com a "conversão" interrompida) liberado.
    assert not list(env.download_dir.rglob("*.mp3"))
    assert _temp_empty(env)


async def test_extraction_error_is_classified_and_row_removed(make_l2_env):
    """Extração falhou (bot-check) → FAILED com o rótulo e a ação; linha some.

    T11-R4: o yt-dlp real embrulha a falha de extração num ``DownloadError``
    (mensagem estável); o worker a rotula como ``ExtractionError`` — o
    detalhe original fica preservado na mensagem mascarada.
    """
    env = make_l2_env(mode="extract-error")

    task = _queue(env, "vid-erro")
    assert env.store.find(task.id) is not None  # linha persistida na fila

    result = await env.manager.download(task)

    assert result.status is DownloadStatus.FAILED
    assert "Sign in to confirm" in (result.error or "")
    assert (result.error or "").startswith("Falha de extração: ")
    assert "nada foi baixado nem publicado" in (result.error or "")
    assert env.store.find(task.id) is None  # terminal não deixa linha
    assert not list(env.download_dir.rglob("*.mp3"))
    assert _temp_empty(env)


@pytest.mark.parametrize("mode", ["missing", "empty"])
async def test_unexpected_output_fails_without_publishing(mode, tmp_path, monkeypatch, make_l2_env):
    """Fidelidade da infraestrutura: "sem saída" × "saída vazia" são distintos.

    Sem cobertura nova (a L1 já cobre os dois): o valor aqui é garantir que
    os modos do stub atravessam o fluxo REAL de reserva/validação/publicação
    sem passar por engano um pelo outro.
    """
    install_fake_ffmpeg(tmp_path, monkeypatch)
    env = make_l2_env(mode=mode)

    result = await env.manager.download(_queue(env, f"vid-{mode}"))

    assert result.status is DownloadStatus.FAILED
    assert "Falha na publicação" in (result.error or "")
    assert not list(env.download_dir.rglob("*.mp3"))
    assert _temp_empty(env)


@pytest.mark.skipif(not Path("/dev/full").exists(), reason="precisa de /dev/full")
async def test_real_enospc_is_classified_and_publishes_nothing(tmp_path, monkeypatch, make_l2_env):
    """Disco cheio com ENOSPC REAL do kernel (/dev/full) → FAILED claro."""
    install_fake_ffmpeg(tmp_path, monkeypatch)
    env = make_l2_env(mode="enospc")

    result = await env.manager.download(_queue(env, "vid-full"))

    assert result.status is DownloadStatus.FAILED
    assert "No space left on device" in (result.error or "")
    assert not list(env.download_dir.rglob("*.mp3"))
    assert _temp_empty(env)


@pytest.mark.asyncio
async def test_quit_com_download_em_voo_fica_interrompido_na_proxima_sessao(
    tmp_path, monkeypatch, make_l2_env
):
    """T12-R4: Ctrl+Q durante o download → INTERRUPTED na sessão seguinte.

    Prova irmã da morte súbita (``test_process_death_l2``): aqui o
    encerramento é GRACIOSO e a ordem real do Textual aparece — os workers
    são cancelados **antes** do Unmount, então o gatilho é o cancelamento da
    corrotina (INTERRUPTED + abort, restaurado no T12-R4); o ``shutdown`` do
    on_unmount corre depois. A sessão seguinte é um **manager novo sobre o
    mesmo banco**: exercita ``recover_interrupted`` do zero, como no próximo
    start do app.
    """
    install_fake_ffmpeg(tmp_path, monkeypatch)
    started = threading.Event()

    class SlowYoutubeDL:
        """Stub lento e cooperativo: dispara os hooks REAIS até o abort."""

        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            template = self.opts["outtmpl"]
            partial = Path(template.replace("%(ext)s", "webm.part"))
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b"parcial")
            started.set()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                for hook in self.opts.get("progress_hooks", []):
                    hook({"status": "downloading", "_percent_str": "1.0%"})
                time.sleep(0.02)
            raise FakeDownloadError("stub não observou o abort (teste)")

    monkeypatch.setattr(
        download_mod,
        "_load_yt_dlp",
        lambda: SimpleNamespace(utils=FakeUtils, YoutubeDL=SlowYoutubeDL),
    )

    env = make_l2_env(mode=None)

    # O app usa o singleton global: store e executor apontam para o ambiente
    # isolado (mesmo padrão do e2e da suíte L1, que injeta executor vivo).
    manager = download_mod.download_manager
    monkeypatch.setattr(manager, "_store", env.store)
    live_executor = ThreadPoolExecutor(max_workers=2)
    monkeypatch.setattr(manager, "_executor", live_executor)

    app = YTMusicTUI()
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert screen._enqueue_download(TrackInfo(video_id="vid-quit", title="Faixa longa"))
            assert await asyncio.to_thread(started.wait, 10), "o worker real não chegou a baixar"
            task = manager._active_downloads.get("vid-quit")
            assert task is not None

            await pilot.press("ctrl+q")
            await pilot.pause()

        assert app.return_code == 0  # a saída não trava com o download em voo
        # T12-R4: o cancelamento dos workers (que precede o Unmount) já marcou
        # INTERRUPTED e acordou o abort; o thread cooperativo sai no próximo
        # hook — a linha persistida espera a decisão da próxima sessão.
        assert task.status is DownloadStatus.INTERRUPTED
        assert task.abort_event.is_set()
    finally:
        live_executor.shutdown(wait=True, cancel_futures=True)

    # Sessão seguinte: manager NOVO sobre o MESMO banco (caminho real).
    fresh = download_mod.DownloadManager(store=DownloadTaskStore(db=env.db))
    try:
        assert fresh.recover_interrupted() == 1
        interrupted = [
            task for task in fresh.get_queue() if task.status is DownloadStatus.INTERRUPTED
        ]
        assert [task.video_id for task in interrupted] == ["vid-quit"]
    finally:
        fresh.shutdown()
