"""Testes de recuperação de downloads interrompidos (T04-R2/R3; §6 do plano).

Cobrem os cenários do §6 que dependem do espelho persistido:
- queda de rede no meio do stream → FAILED, linha removida, nada publicado
  (nunca sucesso falso — INV-1);
- kill -9 no meio → a linha em voo vira INTERRUPTED na execução seguinte e
  o estado é detectável (criterion (b) do §6);
- retomar (r) = nova tarefa com ``retry_of``; temporários antigos (inclusive
  o lock ``.reserva`` órfão) são descartados com log e a lista fica só com a
  nova tarefa (sem INTERRUPTED órfã);
- descartar (d) = limpeza explícita dos temporários próprios + linha
  removida; o arquivo final nunca é tocado;
- encerramento gracioso (shutdown) persiste INTERRUPTED; a próxima sessão
  oferece a decisão;
- cancelamento da corrotina do worker (ordem real do Textual ao fechar o
  app: ``cancel_all`` antes do Unmount) também marca INTERRUPTED e acorda o
  abort (T12-R4);
- falha de escrita no SQLite é tolerada e logada (nunca quebra o download).
"""

import asyncio
import logging
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import ytmusic_tui.download as download_mod
from ytmusic_tui.download import DownloadManager, DownloadStatus, DownloadTask
from ytmusic_tui.download.pipeline import reservation_key
from ytmusic_tui.download.store import DownloadTaskStore
from ytmusic_tui.library.database import DatabaseManager


class _FakeDownloadError(Exception):
    pass


class _FakeUtils:
    DownloadError = _FakeDownloadError


def _fake_ytdlp(youtube_dl_cls) -> SimpleNamespace:
    """Módulo yt_dlp falso em torno de uma classe YoutubeDL."""
    return SimpleNamespace(utils=_FakeUtils, YoutubeDL=youtube_dl_cls)


class _OkYoutubeDL:
    """Baixa e "converte" com sucesso (fim do caminho do worker)."""

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


def _network_failure_youtube_dl(wrote: threading.Event):
    """Fake que baixa parcial e "cai a conexão" (§6, cenário 1)."""

    class _NetworkFailureYoutubeDL:
        def __init__(self, opts: dict):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls: list[str]) -> None:
            template = self.opts["outtmpl"]
            partial = Path(template.replace("%(ext)s", "webm"))
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b"parcial")
            wrote.set()
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading", "_percent_str": "37%"})
            raise _FakeDownloadError("queda de conexão no meio do stream")

    return _NetworkFailureYoutubeDL


def _slow_youtube_dl(release: threading.Event):
    """Fake cooperativo: segura "baixando" até liberar/encerrar (padrão T02)."""

    class _SlowYoutubeDL:
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

            while not release.is_set():
                for hook in self.opts["progress_hooks"]:
                    hook({"status": "downloading", "_percent_str": "50%"})
                time.sleep(0.01)

            for hook in self.opts.get("post_hooks", []):
                hook(str(final))

    return _SlowYoutubeDL


async def _wait_until(condition, timeout: float = 5.0) -> None:
    """Espera (sem bloquear o loop de eventos) até ``condition()`` ser verdadeira."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condição não ficou verdadeira no prazo")
        await asyncio.sleep(0.005)


@pytest.fixture
def temp_db():
    """Banco temporário — os testes nunca tocam o banco real do usuário."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = Path(handle.name)

    db_manager = DatabaseManager(db_path)
    db_manager.create_all()

    yield db_manager

    db_manager.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def store(temp_db) -> DownloadTaskStore:
    return DownloadTaskStore(db=temp_db)


@pytest.fixture
def manager(monkeypatch, tmp_path, store):
    """DownloadManager isolado: settings temporárias, yt-dlp falso e store temp."""
    fake_settings = SimpleNamespace(
        download_dir=tmp_path,
        download_format="mp3",
        download_quality="320",
        embed_metadata=True,
        download_concurrent=1,
    )
    monkeypatch.setattr(download_mod, "settings", fake_settings)
    monkeypatch.setattr(download_mod, "_load_yt_dlp", lambda: _fake_ytdlp(_OkYoutubeDL))
    return DownloadManager(store=store)


def _final(tmp_path: Path) -> Path:
    return tmp_path / "A" / "Alb" / "T - A.mp3"


# ===== Cenário 1: queda de rede no meio do stream =====


@pytest.mark.asyncio
async def test_network_drop_fails_removes_row_and_leaves_no_temp(
    manager, store, tmp_path, monkeypatch
):
    """Cai a conexão: FAILED, linha terminal removida, temporário liberado."""
    wrote = threading.Event()
    monkeypatch.setattr(
        download_mod, "_load_yt_dlp", lambda: _fake_ytdlp(_network_failure_youtube_dl(wrote))
    )

    task = manager.queue_download(video_id="abc", title="T", artist="A", album="Alb", track_id=7)
    result = await manager.download(task)

    assert wrote.is_set()  # o download realmente começou antes de cair
    assert result.status is DownloadStatus.FAILED  # nunca sucesso falso (INV-1)
    assert not _final(tmp_path).exists()
    assert store.find(task.id) is None  # terminal não deixa linha
    assert list((tmp_path / ".tmp").iterdir()) == []  # sem sobras


# ===== Cenário 5: kill -9 no meio + retomada (r) =====


def test_kill9_row_recovers_and_retry_discards_orphans(manager, store, tmp_path, monkeypatch):
    """kill -9: a linha em voo vira INTERRUPTED e retomar limpa os órfãos.

    O processo morto não deixa ninguém para limpar: sobram o lock
    ``.reserva`` (que bloquearia a nova reserva), o ``.part`` em ``.tmp`` e
    o ``.ytdl`` do yt-dlp. Retomar = nova tarefa (novo id, ``retry_of``) com
    o descarte logado desses arquivos — nunca reaproveitar o parcial.
    """
    # Sessão 1 (simulada): tarefa em voo persistida; o processo morre sem limpar.
    task = DownloadTask(
        video_id="abc", title="T", artist="A", album="Alb", track_id=5, id="task-kill9"
    )
    task.transition_to(DownloadStatus.RUNNING)
    final = _final(tmp_path)
    store.save(task, download_dir=tmp_path, final_path=final)

    tmp_dir = tmp_path / ".tmp"
    tmp_dir.mkdir()
    key = reservation_key(final)
    lock = tmp_dir / f"{key}.reserva"
    lock.write_bytes(b"")
    partial = tmp_dir / f"{key}.webm.part"
    partial.write_bytes(b"parcial")
    legacy = Path(f"{final}.ytdl")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"{}")

    # Sessão 2: recupera e retoma.
    assert manager.recover_interrupted() == 1
    recovered = manager.get_queue()[0]
    assert recovered.id == "task-kill9"
    assert recovered.status is DownloadStatus.INTERRUPTED
    row = store.find("task-kill9")
    assert row is not None and row.status == DownloadStatus.INTERRUPTED.value

    monkeypatch.setattr(download_mod.library, "update_track_file", lambda *a, **k: None)
    new_task = manager.retry_interrupted("task-kill9")

    assert new_task is not None
    assert new_task.retry_of == "task-kill9"
    assert new_task.id != "task-kill9"
    # A lista fica só com a nova tentativa: sem INTERRUPTED órfã do mesmo vídeo
    assert [t.id for t in manager.get_queue()] == [new_task.id]
    # Temporários antigos descartados (inclusive o lock que bloquearia a reserva)
    assert not lock.exists() and not partial.exists() and not legacy.exists()
    # Linha antiga removida; a nova nasce PENDING no espelho
    assert store.find("task-kill9") is None
    new_row = store.find(new_task.id)
    assert new_row is not None and new_row.status == DownloadStatus.PENDING.value

    # E a nova tentativa roda o fluxo completo até COMPLETED
    result = manager._download_task(new_task)
    assert result.status is DownloadStatus.COMPLETED
    assert final.exists()


def test_retry_does_not_touch_final_file(manager, store, tmp_path, monkeypatch):
    """O arquivo final do usuário nunca é removido por retomar (política §5.3)."""
    task = DownloadTask(
        video_id="abc", title="T", artist="A", album="Alb", track_id=5, id="task-final"
    )
    task.transition_to(DownloadStatus.RUNNING)
    task.transition_to(DownloadStatus.INTERRUPTED)
    final = _final(tmp_path)
    final.parent.mkdir(parents=True)
    final.write_bytes(b"audio-do-usuario")
    store.save(task, download_dir=tmp_path, final_path=final)

    assert manager.recover_interrupted() == 1
    monkeypatch.setattr(download_mod.library, "update_track_file", lambda *a, **k: None)
    new_task = manager.retry_interrupted("task-final")

    assert new_task is not None
    assert final.exists() and final.read_bytes() == b"audio-do-usuario"


# ===== Diferença de hidratação: linha PENDING não se perde =====


def test_pending_row_is_hydrated_as_interrupted(manager, store, tmp_path):
    """Linha PENDING (morreu antes de começar) vira INTERRUPTED por hidratação.

    PENDING→INTERRUPTED não existe na máquina (§4.2, INTERRUPTED só sai de
    RUNNING/VALIDATING): reconstruir o passado é hidratar direto no estado
    persistido, não transicionar. O item enfileirado não se perde e a
    recuperação é idempotente.
    """
    task = DownloadTask(video_id="abc", title="T", id="task-pend")
    store.save(task, download_dir=tmp_path, final_path=tmp_path / "T.mp3")

    assert manager.recover_interrupted() == 1

    recovered = manager.get_queue()[0]
    assert recovered.id == "task-pend"
    assert recovered.status is DownloadStatus.INTERRUPTED
    row = store.find("task-pend")
    assert row is not None and row.status == DownloadStatus.INTERRUPTED.value

    # Idempotente: recuperar de novo não duplica nem transiciona de novo
    assert manager.recover_interrupted() == 0
    assert [t.id for t in manager.get_queue()] == ["task-pend"]


# ===== Cenário 7: encerramento gracioso + decisão na próxima sessão =====


@pytest.mark.asyncio
async def test_shutdown_persists_interrupted_and_next_session_discards(
    manager, store, tmp_path, monkeypatch
):
    """shutdown marca INTERRUPTED; a próxima sessão oferece r/d e o d limpa tudo."""
    release = threading.Event()
    monkeypatch.setattr(
        download_mod, "_load_yt_dlp", lambda: _fake_ytdlp(_slow_youtube_dl(release))
    )

    task = manager.queue_download(video_id="abc", title="T", artist="A", album="Alb", track_id=5)
    runner = asyncio.create_task(manager.download(task))
    await _wait_until(lambda: task.status is DownloadStatus.RUNNING)

    manager.shutdown()
    await asyncio.wait_for(runner, timeout=5.0)
    assert task.status is DownloadStatus.INTERRUPTED

    row = store.find(task.id)
    assert row is not None and row.status == DownloadStatus.INTERRUPTED.value

    # "Próxima sessão": manager novo sobre o mesmo banco/espelho.
    manager2 = DownloadManager(store=store)
    assert manager2.recover_interrupted() == 1
    recovered = manager2.get_queue()[0]
    assert recovered.id == task.id
    assert recovered.status is DownloadStatus.INTERRUPTED

    # O release() do shutdown já limpou o que a tarefa tinha; sobra semeada
    # (ex.: `.part` legado) é removida pelo descarte explícito.
    sobra = Path(f"{task.file_path or _final(tmp_path)}.part")
    sobra.parent.mkdir(parents=True, exist_ok=True)
    sobra.write_bytes(b"parcial")

    discarded = manager2.discard_interrupted(task.id)

    assert discarded == [sobra]
    assert not sobra.exists()
    assert manager2.get_queue() == []
    assert store.find(task.id) is None


# ===== Cenário 8: cancelamento do worker na saída do app (T12-R4) =====


@pytest.mark.asyncio
async def test_cancellation_of_worker_marks_interrupted_like_shutdown(manager, store, monkeypatch):
    """T12-R4: cancelar a corrotina (Textual: cancel_all antes do Unmount).

    Ordem real do fechamento do app: o ``shutdown`` do ``on_unmount`` roda
    depois do cancelamento e encontraria ``_active_downloads`` vazio — sem
    este caminho o thread seguiria baixando e a linha só viraria INTERRUPTED
    na sessão seguinte. Aqui: INTERRUPTED na hora, abort observado pelo
    thread real, linha persistida.
    """
    abort_seen = threading.Event()

    class _AbortAwareYoutubeDL:
        """Stub lento que registra a saída pelo abort (hook levanta)."""

        def __init__(self, opts: dict):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls: list[str]) -> None:
            try:
                while True:  # só sai quando o abort_event levanta o hook
                    for hook in self.opts["progress_hooks"]:
                        hook({"status": "downloading", "_percent_str": "50%"})
                    time.sleep(0.01)
            except RuntimeError:
                abort_seen.set()
                raise

    monkeypatch.setattr(download_mod, "_load_yt_dlp", lambda: _fake_ytdlp(_AbortAwareYoutubeDL))

    task = manager.queue_download(video_id="abc", title="T", artist="A", album="Alb")
    runner = asyncio.create_task(manager.download(task))
    await _wait_until(lambda: task.status is DownloadStatus.RUNNING)

    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner

    assert task.status is DownloadStatus.INTERRUPTED
    assert task.abort_event.is_set()
    row = store.find(task.id)
    assert row is not None and row.status == DownloadStatus.INTERRUPTED.value

    # Thread real: observar o abort no próximo progress_hook (e sair sem
    # sobrescrever o estado, T02-R3) — a latência de saída documentada.
    await _wait_until(abort_seen.is_set)
    assert task.status is DownloadStatus.INTERRUPTED


# ===== Cenário 6: falha de escrita no SQLite =====


def test_sqlite_write_failure_is_logged_not_fatal(manager, store, monkeypatch, caplog):
    """Banco travado/cheio: o download segue e a falha fica no log (nunca muda)."""

    def _boom(*args, **kwargs):
        raise OSError("database is locked")

    monkeypatch.setattr(store, "save", _boom)
    monkeypatch.setattr(store, "update_status", _boom)
    monkeypatch.setattr(store, "delete", _boom)
    monkeypatch.setattr(download_mod.library, "update_track_file", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING, logger="ytmusic_tui.download"):
        task = manager.queue_download(
            video_id="abc", title="T", artist="A", album="Alb", track_id=7
        )
        result = manager._download_task(task)

    assert result.status is DownloadStatus.COMPLETED  # o download não quebrou
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Falha ao persistir" in message for message in warnings)


def test_recover_failure_is_logged_and_does_not_break_startup(manager, store, monkeypatch, caplog):
    """Espelho ilegível não pode impedir o app de abrir (só avisa no log)."""

    def _boom(*args, **kwargs):
        raise OSError("database disk image is malformed")

    monkeypatch.setattr(store, "mark_active_as_interrupted", _boom)

    with caplog.at_level(logging.WARNING, logger="ytmusic_tui.download"):
        assert manager.recover_interrupted() == 0

    assert any("Falha ao recuperar" in r.getMessage() for r in caplog.records)
    assert manager.get_queue() == []


# ===== Guardas de r/d e fallbacks =====


def test_retry_and_discard_refuse_non_interrupted_and_unknown(manager, store):
    """r/d só agem em INTERRUPTED da fila; qualquer outro id devolve ``None``."""
    task = manager.queue_download(video_id="abc", title="T")
    task.transition_to(DownloadStatus.RUNNING)

    assert manager.retry_interrupted(task.id) is None
    assert manager.discard_interrupted(task.id) is None
    assert manager.retry_interrupted("task-inexistente") is None
    assert manager.discard_interrupted("task-inexistente") is None
    assert task in manager.get_queue()  # nada mudou


def test_retry_without_persisted_row_falls_back_to_template(manager, store, tmp_path, monkeypatch):
    """Sem linha no espelho (falha de escrita), o template atual localiza tudo."""
    task = DownloadTask(
        video_id="abc", title="T", artist="A", album="Alb", track_id=5, id="task-sem-linha"
    )
    task.status = DownloadStatus.INTERRUPTED  # hidratação simulada (sem linha no banco)
    manager._queue.append(task)

    new_task = manager.retry_interrupted("task-sem-linha")

    assert new_task is not None and new_task.retry_of == "task-sem-linha"
    row = store.find(new_task.id)
    assert row is not None
    assert row.final_path == str(_final(tmp_path))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
