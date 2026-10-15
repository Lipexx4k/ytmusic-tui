"""Player de áudio usando mpv (biblioteca libmpv via python-mpv)."""
import contextlib
import locale
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import mpv

from ytmusic_tui.config import settings


class PlayerState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    LOADING = "loading"
    ERROR = "error"


@dataclass
class TrackInfo:
    """Informações da faixa em reprodução."""
    video_id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0.0
    position: float = 0.0
    thumbnail_url: str = ""
    source_url: str = ""  # URL de stream


@dataclass
class PlayerEvent:
    """Evento do player."""
    event: str
    data: dict[str, Any] = field(default_factory=dict)


class MPVPlayer:
    """Wrapper do mpv (libmpv) com observers e eventos."""

    # Formatos de stream por nível de qualidade (settings.mpv_audio_quality).
    AUDIO_QUALITY_FORMATS = {
        "low": "worstaudio/worst",
        "medium": "bestaudio[abr<=96]/bestaudio",
        "high": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
        "best": "bestaudio/best",
    }

    def __init__(self):
        self._mpv: mpv.MPV | None = None
        self._state = PlayerState.STOPPED
        self._current_track: TrackInfo | None = None
        self._callbacks: list[Callable[[PlayerEvent], None]] = []
        self._observers_started = False
        self._last_position_emit = 0.0
        self.last_event_error: str | None = None

    def _ensure_mpv_started(self) -> None:
        """Garante que mpv está rodando."""
        if self._mpv is not None:
            return

        player_kwargs = {
            "vo": "null",  # Sem vídeo
            "audio_client_name": "ytmusic-tui",
            "volume": settings.mpv_volume,
            "ytdl": True,
            "ytdl_format": self._ytdl_format(),
            "force_window": False,
            "keep_open": True,
            "idle": True,
        }

        # O hook ytdl do mpv usa por padrão um youtube-dl embutido e
        # desatualizado, rejeitado pelo YouTube. Apontamos para o yt-dlp
        # atual do projeto para permitir reprodução de streams reais.
        # (python-mpv exige o valor como string "chave=valor".)
        yt_dlp_path = self._find_yt_dlp()
        if yt_dlp_path:
            player_kwargs["script_opts"] = f"ytdl_hook-ytdl_path={yt_dlp_path}"

        # IMPORTANTE: o ytmusicapi muda o locale (LC_ALL) para en_US.UTF-8 no
        # construtor do YTMusic. O libmpv exige LC_NUMERIC="C" — qualquer outro
        # locale (ex.: vírgula decimal) faz o mpv abortar com segfault ao criar
        # o handle (observado em ambiente com LANG=en_US.UTF-8).
        locale.setlocale(locale.LC_NUMERIC, "C")

        self._mpv = mpv.MPV(**player_kwargs)

        # Configurar observadores
        self._setup_observers()
        self._observers_started = True

    def _ytdl_format(self) -> str:
        """Formato de stream do yt-dlp conforme a qualidade configurada."""
        return self.AUDIO_QUALITY_FORMATS.get(
            settings.mpv_audio_quality, self.AUDIO_QUALITY_FORMATS["high"]
        )

    def apply_audio_quality(self) -> None:
        """Aplica a qualidade configurada ao mpv em execução (se possível)."""
        if self._mpv:
            with contextlib.suppress(Exception):
                self._mpv.ytdl_format = self._ytdl_format()

    @staticmethod
    def _find_yt_dlp() -> str | None:
        """Localiza o yt-dlp atualizado para o hook do mpv.

        Prioridade: o script do próprio ambiente Python (ex.: .venv/bin/yt-dlp,
        a versão gerida pelo pip) e só depois qualquer binário no ``PATH``.
        Um yt-dlp antigo do sistema (ex.: /usr/bin/yt-dlp) costuma ser
        rejeitado pelo YouTube, fazendo o stream falhar silenciosamente.
        """
        # sys.executable pode ser um symlink (ex.: .venv/bin/python -> /usr/bin).
        # Não usar .resolve(), senão caímos no binário do sistema.
        sibling = Path(sys.executable).parent / "yt-dlp"
        if sibling.is_file():
            return str(sibling)
        exe = shutil.which("yt-dlp")
        if exe:
            return exe
        return None

    def _setup_observers(self) -> None:
        """Configura observadores de propriedades do mpv."""
        if not self._mpv:
            return

        @self._mpv.property_observer("time-pos")
        def _on_time_pos(_name, value):
            if value is not None and self._current_track:
                self._current_track.position = value
                # O mpv dispara time-pos a cada tick; limitar a ~4 eventos/s
                # evita flood de atualizações na UI.
                now = time.monotonic()
                if now - self._last_position_emit >= 0.25:
                    self._last_position_emit = now
                    self._emit(
                        "position",
                        {"position": value, "duration": self._current_track.duration},
                    )

        @self._mpv.property_observer("duration")
        def _on_duration(_name, value):
            if value is not None and self._current_track:
                self._current_track.duration = value
                self._emit("duration", {"duration": value})

        @self._mpv.property_observer("pause")
        def _on_pause(_name, value):
            if value is not None:
                if value:
                    self._state = PlayerState.PAUSED
                    self._emit("pause", {})
                else:
                    self._state = PlayerState.PLAYING
                    self._emit("resume", {})

        @self._mpv.property_observer("idle-active")
        def _on_idle(_name, value):
            if value and self._state != PlayerState.STOPPED:
                self._state = PlayerState.STOPPED
                self._current_track = None
                self._emit("ended", {})

        @self._mpv.event_callback("end-file")
        def _on_end_file(event):
            # python-mpv entrega um MpvEvent (não um dict). Usamos as_dict()
            # para acessar os campos de forma segura.
            try:
                data = event.as_dict()
            except Exception:
                return
            reason = data.get("reason")
            if reason == "eof":
                self._emit("track_ended", {"reason": "eof"})
            elif reason == "error":
                self._state = PlayerState.ERROR
                self._emit("error", {"message": data.get("error", "Erro desconhecido")})

    def _emit(self, event: str, data: dict[str, Any] = None) -> None:
        """Emite evento para callbacks registrados."""
        player_event = PlayerEvent(event=event, data=data or {})
        for callback in self._callbacks:
            try:
                callback(player_event)
            except Exception as e:
                # Nunca imprimir na TUI; guardar para diagnóstico.
                self.last_event_error = str(e)

    def on_event(self, callback: Callable[[PlayerEvent], None]) -> None:
        """Registra callback para eventos do player."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[PlayerEvent], None]) -> None:
        """Remove callback registrado."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    @property
    def state(self) -> PlayerState:
        return self._state

    @property
    def current_track(self) -> TrackInfo | None:
        return self._current_track

    def play(self, track_info: TrackInfo) -> bool:
        """Inicia reprodução de uma faixa."""
        self._ensure_mpv_started()

        if not self._mpv:
            return False

        try:
            self._state = PlayerState.LOADING
            self._emit("loading", {"track": track_info})

            # Carregar URL no mpv
            self._mpv.play(track_info.source_url)

            self._current_track = track_info
            self._state = PlayerState.PLAYING
            self._emit("play", {"track": track_info})
            return True

        except Exception as e:
            self._state = PlayerState.ERROR
            self._emit("error", {"message": str(e)})
            return False

    def pause(self) -> None:
        """Pausa reprodução."""
        if self._mpv:
            self._mpv.pause = True

    def resume(self) -> None:
        """Retoma reprodução."""
        if self._mpv:
            self._mpv.pause = False

    def toggle_pause(self) -> None:
        """Alterna pause/play."""
        if self._mpv:
            self._mpv.pause = not self._mpv.pause

    def stop(self) -> None:
        """Para reprodução."""
        if self._mpv:
            self._mpv.stop()
            self._state = PlayerState.STOPPED
            self._current_track = None
            self._emit("stop", {})

    def seek(self, position: float) -> None:
        """Busca para posição (segundos)."""
        if self._mpv and self._current_track:
            self._mpv.seek(position, reference="absolute")

    def seek_relative(self, seconds: float) -> None:
        """Busca relativa (segundos)."""
        if self._mpv:
            self._mpv.seek(seconds, reference="relative")

    def set_volume(self, volume: int) -> None:
        """Define volume (0-100)."""
        if self._mpv:
            self._mpv.volume = max(0, min(100, volume))

    def get_volume(self) -> int:
        """Obtém volume atual."""
        if self._mpv:
            return int(self._mpv.volume or 0)
        return settings.mpv_volume

    def next_track(self) -> None:
        """Próxima faixa (emite evento para queue manager)."""
        self._emit("next", {})

    def previous_track(self) -> None:
        """Faixa anterior."""
        self._emit("previous", {})

    def set_speed(self, speed: float) -> None:
        """Define velocidade de reprodução."""
        if self._mpv:
            self._mpv.speed = max(0.25, min(4.0, speed))

    def get_property(self, name: str) -> Any:
        """Obtém propriedade do mpv."""
        if self._mpv:
            return getattr(self._mpv, name, None)
        return None

    def shutdown(self) -> None:
        """Encerra player completamente."""
        if self._mpv:
            with contextlib.suppress(Exception):
                self._mpv.terminate()
            self._mpv = None
        self._state = PlayerState.STOPPED
        self._current_track = None


# Instância global
player = MPVPlayer()