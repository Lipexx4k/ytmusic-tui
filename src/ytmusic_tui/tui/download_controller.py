"""Ações de download na TUI (mixin de ``MainScreen``)."""

from typing import TYPE_CHECKING, Any

from textual.widgets import DataTable

from ytmusic_tui.download import DownloadStatus, DownloadTask, download_manager
from ytmusic_tui.library import library
from ytmusic_tui.player import TrackInfo, player

if TYPE_CHECKING:
    from collections.abc import Callable


class DownloadController:
    """Mixin da aba 📥 Downloads e dos atalhos Ctrl+D / A.

    A classe host (``MainScreen``) oferece ``_toast`` e mantém
    ``_current_album`` (usado pelo "a"); ``_track_info_from_song``
    (PlaybackController) e ``refresh_library`` (LibraryController) também
    vêm dos mixins do mesmo host.
    """

    # Estado e membros fornecidos pela tela host (o mypy analisa cada mixin
    # isoladamente; as declarações abaixo existem só na checagem de tipos).
    _current_album: dict | None
    if TYPE_CHECKING:

        def query_one(self, selector: Any, expect_type: Any = None) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...
        def _toast(self, message: str) -> None: ...
        def refresh_library(self) -> None: ...

        _track_info_from_song: Callable[..., Any]

    # ===== Tabela de downloads =====

    def update_downloads_table(self) -> None:
        """Atualiza tabela de downloads."""
        try:
            table = self.query_one("#downloads-table", DataTable)
        except Exception:
            # A aba de downloads não está montada no momento.
            return
        table.clear(columns=True)
        table.add_columns("Status", "Título", "Artista", "Progresso", "Velocidade", "ETA")

        all_tasks = download_manager.get_queue() + download_manager.get_active_downloads()
        for task in all_tasks:
            status_icon = {
                DownloadStatus.PENDING: "⏳",
                DownloadStatus.DOWNLOADING: "⬇️",
                DownloadStatus.COMPLETED: "✅",
                DownloadStatus.FAILED: "❌",
                DownloadStatus.CANCELLED: "🚫",
            }.get(task.status, "?")
            table.add_row(
                status_icon,
                task.title[:40],
                task.artist[:30],
                f"{task.progress:.1f}%" if task.progress else "—",
                task.speed,
                task.eta,
            )

    # ===== Ações =====

    def action_download(self) -> None:
        """Baixa faixa atual."""
        # Sem guard aqui: `download_current_track` já valida e avisa o usuário
        # ("Nenhuma faixa em reprodução") — antes o Ctrl+D era ignorado em
        # silêncio quando não havia faixa tocando.
        self.download_current_track()

    def action_download_album(self) -> None:
        """Baixa todas as faixas do álbum aberto na aba 💿 Álbum (tecla "a")."""
        if not self._current_album:
            self._toast("Nenhum álbum aberto — selecione um álbum na busca")
            return
        self.download_album(self._current_album)

    def download_current_track(self) -> None:
        """Baixa a faixa em reprodução."""
        track = player.current_track
        if not track or not track.video_id:
            self._toast("Nenhuma faixa em reprodução")
            return
        self._enqueue_download(track)

    def download_album(self, album: dict) -> None:
        """Enfileira o download de todas as faixas do álbum.

        Faixas já baixadas (na biblioteca local) são puladas; um único toast
        resume o resultado em vez de um por faixa.
        """
        tracks = [
            track
            for track in (album.get("tracks") or [])
            if track.get("videoId") and track.get("isAvailable", True)
        ]
        if not tracks:
            self._toast("Álbum sem faixas para baixar")
            return

        album_title = album.get("title", "")
        queued = 0
        skipped = 0
        in_progress = 0
        for track_data in tracks:
            info = self._track_info_from_song(track_data)
            if not info.video_id:
                continue
            if not info.album:
                info.album = album_title
            existing = library.get_track_by_source_id(info.video_id)
            if existing and existing.is_downloaded:
                skipped += 1
                continue
            if self._enqueue_download(info, notify=False):
                queued += 1
            else:
                in_progress += 1

        parts = []
        if queued:
            parts.append(f"{queued} faixa(s) enfileirada(s)")
        if in_progress:
            parts.append(f"{in_progress} já em andamento")
        if skipped:
            parts.append(f"{skipped} já baixada(s)")
        self._toast(f"💿 {album_title}: {', '.join(parts) if parts else 'nada novo para baixar'}")

    def _enqueue_download(self, track: TrackInfo, notify: bool = True) -> bool:
        """Registra a faixa na biblioteca e enfileira o download.

        O registro acontece ANTES do download para que o arquivo final já
        fique vinculado (aparece na aba Biblioteca).
        """
        if not track.video_id:
            return False

        if download_manager.is_active_or_pending(track.video_id):
            if notify:
                self._toast(f"⏳ Já na fila: {track.title}")
            return False

        track_id = library.ensure_track(
            source_id=track.video_id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            thumbnail_url=track.thumbnail_url,
            duration_seconds=int(track.duration or 0),
        )

        task = download_manager.queue_download(
            video_id=track.video_id,
            title=track.title,
            artist=track.artist,
            album=track.album or "",
            thumbnail_url=track.thumbnail_url,
            track_id=track_id or 0,
        )
        # Downloads podem ser simultâneos (settings.download_concurrent);
        # sem exclusive=True para não cancelar o worker de outro download.
        self.run_worker(self._run_download(task), group="download")
        if notify:
            self._toast(f"Iniciando download: {track.title}")
        return True

    async def _run_download(self, task: DownloadTask) -> None:
        """Executa download em background."""
        await download_manager.download(task)
        self.update_downloads_table()
        if task.status == DownloadStatus.COMPLETED:
            self._toast(f"✅ Download concluído: {task.title}")
            self.refresh_library()
        elif task.status == DownloadStatus.FAILED:
            self._toast(f"❌ Falha no download: {task.error}")
        elif task.status == DownloadStatus.CANCELLED:
            self._toast(f"Download cancelado: {task.title}")
