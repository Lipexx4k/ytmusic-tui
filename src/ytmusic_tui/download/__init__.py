"""Gerenciador de downloads usando yt-dlp (import tardio)."""

import asyncio
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ytmusic_tui.config import settings
from ytmusic_tui.library.service import library

# O import de yt_dlp é pesado (~0.4s) e não é necessário para abrir a TUI.
# Carregamos sob demanda e guardamos o módulo para reuso/testes.
_yt_dlp_module = None


def _load_yt_dlp():
    """Importa (uma única vez) e devolve o módulo yt_dlp."""
    global _yt_dlp_module
    if _yt_dlp_module is None:
        import yt_dlp

        _yt_dlp_module = yt_dlp
    return _yt_dlp_module


def _truncate_bytes(name: str, max_bytes: int) -> str:
    """Corta ``name`` para caber em ``max_bytes`` (UTF-8) sem quebrar caractere.

    O limite de 255 bytes por componente de caminho (ext4, APFS, NTFS...)
    conta bytes, não caracteres: 100 caracteres CJK ocupam 300 bytes, então
    um corte apenas por caracteres não basta para nomes multibyte.
    """
    encoded = name.encode("utf-8")
    if len(encoded) <= max_bytes:
        return name
    return encoded[:max_bytes].decode("utf-8", errors="ignore").strip(" .")


class DownloadStatus(Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadTask:
    """Tarefa de download."""

    video_id: str
    title: str = ""
    artist: str = ""
    album: str = ""
    thumbnail_url: str = ""
    track_id: int = 0  # ID na biblioteca local
    status: DownloadStatus = DownloadStatus.PENDING
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    file_path: Path | None = None
    error: str = ""
    _future: asyncio.Future | None = field(default=None, repr=False)
    abort_event: threading.Event = field(default_factory=threading.Event, repr=False)


class DownloadManager:
    """Gerencia downloads de músicas do YouTube Music."""

    def __init__(self):
        self._queue: list[DownloadTask] = []
        self._active_downloads: dict[str, DownloadTask] = {}
        self._executor = ThreadPoolExecutor(max_workers=settings.download_concurrent)

    def set_concurrent(self, workers: int) -> None:
        """Recria o executor com novo limite de downloads simultâneos."""
        workers = max(1, min(10, workers))
        old = self._executor
        self._executor = ThreadPoolExecutor(max_workers=workers)
        old.shutdown(wait=False)

    def _sanitize_filename(self, name: str, max_len: int = 120) -> str:
        """Sanitiza nome de arquivo (também limita o tamanho)."""
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
        return name.strip(" .")[:max_len]

    def _get_output_template(self, task: DownloadTask) -> str:
        """Gera template de saída para yt-dlp."""
        # Limites conservadores para não estourar o máximo de 255 bytes por
        # componente do caminho em sistemas de arquivos comuns. O limite é
        # em BYTES: títulos com caracteres multibyte (acentos, CJK, emoji)
        # estouram antes do limite de caracteres, então cortamos também por
        # bytes — com folga para os sufixos do yt-dlp (extensão, .part, .webp).
        artist = self._sanitize_filename(task.artist or "Unknown Artist", 60)
        title = self._sanitize_filename(task.title or "Unknown Title", 100)
        album = self._sanitize_filename(task.album or "Unknown Album", 60)
        artist = _truncate_bytes(artist, 120) or "Unknown Artist"
        album = _truncate_bytes(album, 120) or "Unknown Album"
        stem = _truncate_bytes(f"{title} - {artist}", 240) or "Unknown Title"

        # Estrutura: Artist/Album/Track - Artist.ext
        if album and album != "Unknown Album":
            return str(settings.download_dir / artist / album / f"{stem}.%(ext)s")
        return str(settings.download_dir / artist / f"{stem}.%(ext)s")

    def _get_ydl_options(self, task: DownloadTask) -> dict[str, Any]:
        """Opções do yt-dlp para download."""
        output_template = self._get_output_template(task)

        # Formato de áudio
        format_map = {
            "mp3": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
            "opus": "bestaudio[ext=opus]/bestaudio[ext=webm]/bestaudio",
            "m4a": "bestaudio[ext=m4a]/bestaudio",
            "flac": "bestaudio[ext=flac]/bestaudio",
        }
        audio_format = format_map.get(settings.download_format, "bestaudio")

        opts = {
            "format": audio_format,
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,  # sem isso, o progresso é impresso e corrompe a TUI
            "ignoreerrors": False,
            "extract_flat": False,
            "writethumbnail": settings.embed_metadata,
            "postprocessors": [],
            "progress_hooks": [lambda d: self._progress_hook(task, d)],
            # post_hooks recebem o caminho FINAL (após os post-processadores,
            # ex.: .mp3 convertido) — progress_hooks só têm o arquivo baixado.
            "post_hooks": [lambda path: self._capture_final_path(task, path)],
        }

        # Post-processadores para conversão + metadados/capa
        if settings.download_format == "mp3":
            opts["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": settings.download_quality,
                }
            )
        elif settings.download_format == "opus":
            opts["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "opus",
                    "preferredquality": settings.download_quality,
                }
            )
        elif settings.download_format == "m4a":
            opts["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                }
            )
        elif settings.download_format == "flac":
            opts["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "flac",
                }
            )

        if settings.embed_metadata:
            # O EmbedThumbnail remove o .webp temporário ao terminar (quando
            # "already_have_thumbnail" não é passado) e o FFmpegMetadata grava
            # as tags — ambos válidos para qualquer formato de saída.
            opts["postprocessors"].append(
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                }
            )
            opts["postprocessors"].append(
                {
                    "key": "EmbedThumbnail",
                }
            )

        return opts

    def _capture_final_path(self, task: DownloadTask, path: str) -> None:
        """Guarda o caminho final informado pelo post_hook do yt-dlp."""
        task.file_path = Path(path)

    def _progress_hook(self, task: DownloadTask, data: dict[str, Any]) -> None:
        """Hook de progresso do yt-dlp (roda na thread do executor)."""
        if task.abort_event.is_set():
            # Qualquer exceção em um progress hook aborta o download.
            raise RuntimeError("Download cancelado")

        status = data.get("status")
        if status == "downloading":
            task.status = DownloadStatus.DOWNLOADING
            percent = str(data.get("_percent_str", "0%"))
            try:
                task.progress = float(percent.replace("%", "").strip())
            except ValueError:
                task.progress = 0.0
            task.speed = data.get("_speed_str", "") or ""
            task.eta = data.get("_eta_str", "") or ""
        elif status == "finished":
            # Arquivo baixado; o pós-processamento (conversão, tags) ainda
            # está por vir — o status final é definido em _download_task.
            task.progress = 100.0

    def _download_task(self, task: DownloadTask) -> DownloadTask:
        """Executa download em thread separada."""
        task.status = DownloadStatus.DOWNLOADING
        yt_dlp = _load_yt_dlp()

        url = f"https://music.youtube.com/watch?v={task.video_id}"

        try:
            with yt_dlp.YoutubeDL(self._get_ydl_options(task)) as ydl:
                ydl.download([url])

            if task.abort_event.is_set():
                task.status = DownloadStatus.CANCELLED
                task.error = "Cancelado"
            elif task.file_path and task.file_path.exists():
                if task.track_id:
                    file_size = task.file_path.stat().st_size
                    library.update_track_file(
                        task.track_id,
                        task.file_path,
                        file_size,
                        settings.download_format,
                        int(settings.download_quality)
                        if settings.download_quality.isdigit()
                        else 320,
                    )
                task.status = DownloadStatus.COMPLETED
            else:
                task.status = DownloadStatus.FAILED
                task.error = "Arquivo final não encontrado após o download"

        except Exception as e:
            if task.abort_event.is_set():
                task.status = DownloadStatus.CANCELLED
                task.error = "Cancelado"
            elif isinstance(e, yt_dlp.utils.DownloadError):
                task.status = DownloadStatus.FAILED
                task.error = str(e)
            else:
                task.status = DownloadStatus.FAILED
                task.error = f"Erro inesperado: {e}"

        return task

    async def download(self, task: DownloadTask) -> DownloadTask:
        """Inicia download assíncrono."""
        loop = asyncio.get_running_loop()
        task._future = loop.run_in_executor(self._executor, self._download_task, task)
        self._active_downloads[task.video_id] = task

        try:
            return await task._future
        finally:
            self._active_downloads.pop(task.video_id, None)

    def queue_download(
        self,
        video_id: str,
        title: str = "",
        artist: str = "",
        album: str = "",
        thumbnail_url: str = "",
        track_id: int = 0,
    ) -> DownloadTask:
        """Adiciona à fila de downloads."""
        task = DownloadTask(
            video_id=video_id,
            title=title,
            artist=artist,
            album=album,
            thumbnail_url=thumbnail_url,
            track_id=track_id,
        )
        self._queue.append(task)
        return task

    def cancel_download(self, video_id: str) -> bool:
        """Cancela download ativo ou pendente."""
        task = self._active_downloads.get(video_id)
        if task is None:
            for queued in self._queue:
                if queued.video_id == video_id:
                    task = queued
                    break
        if task is None:
            return False

        task.abort_event.set()
        task.status = DownloadStatus.CANCELLED
        task.error = "Cancelado"
        if task in self._queue and task not in self._active_downloads.values():
            self._queue.remove(task)
        return True

    def get_queue(self) -> list[DownloadTask]:
        """Retorna fila de downloads (ativos + concluídos da sessão)."""
        return self._queue.copy()

    def get_active_downloads(self) -> list[DownloadTask]:
        """Retorna downloads ativos."""
        return list(self._active_downloads.values())

    def is_active_or_pending(self, video_id: str) -> bool:
        """True se o vídeo já está baixando ou aguardando na fila.

        Evita enfileirar o mesmo vídeo duas vezes: dois downloads simultâneos
        disputariam o mesmo arquivo de saída (e o mesmo ``.part``).
        """
        if video_id in self._active_downloads:
            return True
        return any(
            task.video_id == video_id
            and task.status in (DownloadStatus.PENDING, DownloadStatus.DOWNLOADING)
            for task in self._queue
        )

    def clear_completed(self) -> None:
        """Remove downloads concluídos/cancelados da fila."""
        self._queue = [
            t
            for t in self._queue
            if t.status
            not in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, DownloadStatus.FAILED)
        ]

    def shutdown(self) -> None:
        """Encerra gerenciador sem bloquear a saída do app."""
        # Sinaliza aborto; os hooks de progresso interrompem os downloads
        # rapidamente. Evita também que o interpretador espere threads
        # de download em andamento.
        for task in self._active_downloads.values():
            task.abort_event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)


# Instância global
download_manager = DownloadManager()
