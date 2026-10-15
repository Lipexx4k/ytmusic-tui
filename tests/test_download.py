"""Testes do gerenciador de downloads (offline, com yt-dlp falso).

Cobrem as regressões encontradas na revisão de código:
- o caminho final só aparece nos ``post_hooks`` (``progress_hooks`` trazem o
  arquivo baixado, antes da conversão; o task terminava sempre FAILED);
- ``noprogress`` precisa estar ativo (sem isso o yt-dlp imprime sobre a TUI);
- ``EmbedThumbnail``/``FFmpegMetadata`` são post-processadores (as chaves de
  CLI ``embedthumbnail``/``addmetadata`` eram ignoradas);
- cancelamento via ``abort_event`` (``future.cancel()`` não interrompia nada);
- nomes de arquivo limitados para não estourar ENAMETOOLONG.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

import ytmusic_tui.download as download_mod
from ytmusic_tui.download import DownloadStatus, DownloadTask


class _FakeDownloadError(Exception):
    pass


class _FakeUtils:
    DownloadError = _FakeDownloadError


class _FakeYoutubeDL:
    """Simula o ciclo do yt-dlp: baixa, converte e chama os hooks."""

    def __init__(self, opts: dict):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def download(self, urls: list[str]) -> None:
        template = self.opts["outtmpl"]
        intermediate = Path(template.replace("%(ext)s", "webm"))
        intermediate.parent.mkdir(parents=True, exist_ok=True)
        intermediate.write_bytes(b"audio-original")

        for hook in self.opts["progress_hooks"]:
            hook(
                {
                    "status": "downloading",
                    "filename": str(intermediate),
                    "_percent_str": " 42.5%",
                    "_speed_str": "2MiB/s",
                    "_eta_str": "00:03",
                }
            )
        for hook in self.opts["progress_hooks"]:
            hook({"status": "finished", "filename": str(intermediate), "total_bytes": 14})

        # Post-processamento "converte" para o arquivo final
        final = Path(template.replace("%(ext)s", "mp3"))
        final.write_bytes(b"audio-convertido-mp3")
        for hook in self.opts.get("post_hooks", []):
            hook(str(final))


class _FakeYtDlp:
    utils = _FakeUtils
    YoutubeDL = _FakeYoutubeDL


@pytest.fixture
def manager(monkeypatch, tmp_path):
    """DownloadManager com settings isoladas e yt-dlp falso."""
    fake_settings = SimpleNamespace(
        download_dir=tmp_path,
        download_format="mp3",
        download_quality="320",
        embed_metadata=True,
        download_concurrent=1,
    )
    monkeypatch.setattr(download_mod, "settings", fake_settings)
    monkeypatch.setattr(download_mod, "_load_yt_dlp", lambda: _FakeYtDlp)
    return download_mod.DownloadManager()


def test_ydl_options_are_silent_and_embed_metadata(manager):
    """Opções essenciais: silêncio, post_hooks e PPs de metadados/capa."""
    task = DownloadTask(video_id="abc", title="T", artist="A", album="Alb")
    opts = manager._get_ydl_options(task)

    assert opts["quiet"] is True
    assert opts["no_warnings"] is True
    assert opts["noprogress"] is True  # sem isso o yt-dlp escreve na TUI
    assert opts["writethumbnail"] is True
    assert len(opts["post_hooks"]) == 1
    assert len(opts["progress_hooks"]) == 1

    keys = [pp["key"] for pp in opts["postprocessors"]]
    assert keys == ["FFmpegExtractAudio", "FFmpegMetadata", "EmbedThumbnail"]
    # Sem already_have_thumbnail: o .webp temporário é removido ao final
    assert all("already_have_thumbnail" not in pp for pp in opts["postprocessors"])
    # Chaves que só existem na CLI não devem mais ser passadas
    assert "embedthumbnail" not in opts
    assert "addmetadata" not in opts


def test_ydl_options_without_metadata(manager, monkeypatch):
    """Sem embed_metadata não há capa/caminho de imagem nem tags."""
    monkeypatch.setattr(download_mod.settings, "embed_metadata", False)
    opts = manager._get_ydl_options(DownloadTask(video_id="abc"))
    assert opts["writethumbnail"] is False
    keys = [pp["key"] for pp in opts["postprocessors"]]
    assert keys == ["FFmpegExtractAudio"]


def test_output_template_limits_component_length(manager):
    """Título/artista gigantes não podem estourar o limite do filesystem."""
    task = DownloadTask(
        video_id="abc",
        title="T" * 500,
        artist="A" * 500,
        album="L" * 500,
    )
    template = manager._get_output_template(task)
    filename = Path(template).name
    assert len(filename) <= 180  # título(100) + ' - ' + artista(60) + ext


def test_download_task_completes_with_final_path(manager, monkeypatch, tmp_path):
    """O task deve terminar COMPLETED com o caminho pós-conversão."""
    updates: list[tuple] = []
    monkeypatch.setattr(
        download_mod.library,
        "update_track_file",
        lambda *args, **kwargs: updates.append(args),
    )

    task = manager.queue_download(
        video_id="abc", title="T", artist="A", album="Alb", track_id=7
    )
    result = manager._download_task(task)

    assert result.status == DownloadStatus.COMPLETED
    assert result.error == ""
    assert result.progress == 100.0
    assert result.file_path == tmp_path / "A" / "Alb" / "T - A.mp3"
    assert result.file_path.exists()

    # Registro na biblioteca com o caminho final
    assert updates and updates[0][0] == 7
    assert updates[0][1] == result.file_path


def test_progress_hook_does_not_complete_prematurely(manager):
    """'finished' é só o download; a conversão ainda vai rodar."""
    task = DownloadTask(video_id="abc")
    manager._progress_hook(
        task,
        {
            "status": "downloading",
            "_percent_str": " 42.5%",
            "_speed_str": "2MiB/s",
            "_eta_str": "00:03",
        },
    )
    assert task.progress == 42.5
    assert task.speed == "2MiB/s"

    manager._progress_hook(task, {"status": "finished", "filename": "/x.m4a"})
    assert task.progress == 100.0
    assert task.status != DownloadStatus.COMPLETED


def test_cancel_aborts_download(manager):
    """cancel_download precisa sinalizar abort e remover da fila."""
    task = manager.queue_download(video_id="abc", title="T")
    assert manager.cancel_download("abc") is True
    assert task.abort_event.is_set()
    assert task.status == DownloadStatus.CANCELLED
    assert task not in manager.get_queue()

    with pytest.raises(RuntimeError):
        manager._progress_hook(task, {"status": "downloading", "_percent_str": "1%"})

    assert manager.cancel_download("inexistente") is False


def test_download_task_cancelled(manager, monkeypatch):
    """Abort durante o download marca CANCELLED (e não FAILED)."""

    def _download_and_cancel(self, urls):
        for hook in self.opts["progress_hooks"]:
            hook({"status": "downloading", "_percent_str": "10%"})

    task = manager.queue_download(video_id="abc", title="T")
    task.abort_event.set()
    monkeypatch.setattr(_FakeYoutubeDL, "download", _download_and_cancel)

    result = manager._download_task(task)
    assert result.status == DownloadStatus.CANCELLED


def test_shutdown_does_not_block(manager):
    """shutdown não pode travar a saída do app (wait=False + abort)."""
    task = manager.queue_download(video_id="abc", title="T")
    manager._active_downloads[task.video_id] = task
    manager.shutdown()
    assert task.abort_event.is_set()


def test_is_active_or_pending_blocks_duplicates_but_allows_retry(manager):
    """O mesmo vídeo não pode ser enfileirado duas vezes enquanto está ativo."""
    assert manager.is_active_or_pending("x") is False

    task = manager.queue_download(video_id="x", title="T")
    assert manager.is_active_or_pending("x") is True  # pendente na fila
    assert manager.is_active_or_pending("y") is False

    # Finalizado/cancelado/falho libera tentar de novo (retry após erro)
    for final in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, DownloadStatus.FAILED):
        task.status = final
        assert manager.is_active_or_pending("x") is False

    # Baixando agora (fora da fila visível) continua bloqueando
    task.status = DownloadStatus.DOWNLOADING
    manager._active_downloads["x"] = task
    assert manager.is_active_or_pending("x") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
