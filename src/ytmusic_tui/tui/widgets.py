"""Widgets personalizados usados pelas telas da TUI."""

from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, ListItem, ListView, ProgressBar, Static

from ytmusic_tui.api.models import Album, Track
from ytmusic_tui.library.models import Track as LibraryTrack
from ytmusic_tui.player import PlayerState, TrackInfo
from ytmusic_tui.tui.messages import PLAYER_ERROR_TEXT, PLAYER_LOADING_TEXT


class AutoHighlightListView(ListView):
    """``ListView`` que destaca o primeiro item ao receber foco.

    Sem isso, focar a lista pelo teclado (Tab) deixa ``index`` em ``None``
    e o Enter não seleciona nada (o usuário precisaria apertar ↓ antes).
    """

    def on_focus(self) -> None:
        if self.index is None and len(self):
            self.index = 0


class TrackListView(AutoHighlightListView):
    """Lista de faixas da biblioteca local."""

    def __init__(self, tracks: list[LibraryTrack] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tracks: list[LibraryTrack] = []
        self.set_tracks(tracks or [])

    def set_tracks(self, tracks: list[LibraryTrack]) -> None:
        """Atualiza a lista sem remontar o widget (evita ``DuplicateIds``).

        Os itens são recriados in-place; por isso não usam ``id``.
        """
        self.tracks = list(tracks)
        self.clear()
        for track in self.tracks:
            artists = ", ".join(track.artist_names)
            label = f"{track.title} — {artists}" if artists else track.title
            self.append(ListItem(Label(label, markup=False)))

    def get_selected_track(self) -> LibraryTrack | None:
        """Retorna faixa selecionada."""
        if self.index is not None and 0 <= self.index < len(self.tracks):
            return self.tracks[self.index]
        return None


class SearchInput(Input):
    """Input de busca com placeholder."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(placeholder="🔍 Buscar músicas, artistas, álbuns...", **kwargs)


class SongListView(AutoHighlightListView):
    """Lista de músicas (resultados de busca ou faixas de álbum)."""

    def __init__(self, songs: list[Track] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.songs: list[Track] = []
        self.set_songs(songs or [])

    def set_songs(self, songs: list[Track]) -> None:
        """Atualiza os resultados exibidos (in-place, sem ``id`` nos itens)."""
        self.songs = list(songs)
        self.clear()
        for song in self.songs:
            artists = ", ".join(song.artists)
            label = f"{song.title} — {artists}" if artists else song.title
            if song.duration_text:
                label += f"  ({song.duration_text})"
            # markup=False: títulos reais contêm [colchetes] que o Rich
            # interpretaria como marcação (texto sumia ou quebrava).
            self.append(ListItem(Label(label, markup=False)))

    def get_selected_song(self) -> Track | None:
        """Retorna a música selecionada (modelo interno do T10-R1)."""
        if self.index is not None and 0 <= self.index < len(self.songs):
            return self.songs[self.index]
        return None


class AlbumListView(AutoHighlightListView):
    """Lista de álbuns (itens de busca)."""

    def __init__(self, albums: list[Album] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.albums: list[Album] = []
        self.set_albums(albums or [])

    def set_albums(self, albums: list[Album]) -> None:
        """Atualiza a lista exibida (in-place, sem ``id`` nos itens)."""
        self.albums = list(albums)
        self.clear()
        for album in self.albums:
            artists = ", ".join(album.artists)
            kind = album.kind or "Álbum"
            label = f"💿 {album.title}"
            if artists:
                label += f" — {artists}"
            meta = ", ".join(part for part in (kind, album.year) if part)
            label += f"  ({meta})"
            # markup=False: títulos reais contêm [colchetes] que o Rich
            # interpretaria como marcação.
            self.append(ListItem(Label(label, markup=False)))

    def get_selected_album(self) -> Album | None:
        """Retorna o álbum selecionado (modelo interno do T10-R1)."""
        if self.index is not None and 0 <= self.index < len(self.albums):
            return self.albums[self.index]
        return None


class NowPlayingBar(Static):
    """Barra de reprodução atual na parte inferior."""

    DEFAULT_CSS = """
    NowPlayingBar {
        dock: bottom;
        height: 4;
        background: $surface;
        border-top: solid $primary;
        padding: 0 2;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.current_track: TrackInfo | None = None

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("", id="np-info"),
            Horizontal(
                Button("⏮", id="btn-prev", variant="default"),
                Button("⏯", id="btn-play-pause", variant="primary"),
                Button("⏭", id="btn-next", variant="default"),
                id="np-controls",
            ),
            Horizontal(
                Static("0:00", id="np-time-current"),
                ProgressBar(id="np-progress", show_eta=False),
                Static("0:00", id="np-time-total"),
                id="np-progress-container",
            ),
            Static("🔊 50%", id="np-volume"),
            id="np-container",
        )

    def update_track(self, track: TrackInfo) -> None:
        """Atualiza faixa em reprodução."""
        self.current_track = track
        info = self.query_one("#np-info", Static)
        # escape(): o título/artista vêm do YouTube e podem conter [colchetes].
        info.update(f"[b]{escape(track.title)}[/b] — {escape(track.artist)}")

    def update_position(self, position: float, duration: float) -> None:
        """Atualiza posição da reprodução."""
        progress = self.query_one("#np-progress", ProgressBar)
        time_current = self.query_one("#np-time-current", Static)
        time_total = self.query_one("#np-time-total", Static)

        progress.progress = (position / duration * 100) if duration > 0 else 0
        time_current.update(self._format_time(position))
        time_total.update(self._format_time(duration))

    def update_state(self, state: PlayerState) -> None:
        """Atualiza o botão play/pause e o texto de estado (§12.2/T11-R3).

        Estados da §12.2: parado (`stop`/`ended`), **carregando** (`loading`,
        o player emite antes de abrir o stream), tocando (`play`/`resume`),
        pausado (`pause`) e falha (`error`). ``ERROR`` mostra "falha" no lugar
        da faixa e fica visível até o próximo estado (o toast do app traz o
        detalhe mascarado; um novo ``play`` chama ``update_track`` e substitui
        o texto).
        """
        btn = self.query_one("#btn-play-pause", Button)
        if state == PlayerState.PLAYING:
            btn.label = "⏸"
        elif state == PlayerState.LOADING:
            btn.label = "⏳"
        elif state == PlayerState.ERROR:
            btn.label = "⚠"
        else:
            btn.label = "▶"
        if state == PlayerState.ERROR:
            self.query_one("#np-info", Static).update(f"[b]{PLAYER_ERROR_TEXT}[/b]")
        elif state == PlayerState.LOADING:
            self.query_one("#np-info", Static).update(PLAYER_LOADING_TEXT)

    def update_volume(self, volume: int) -> None:
        """Atualiza volume."""
        vol_widget = self.query_one("#np-volume", Static)
        icon = "🔇" if volume == 0 else "🔈" if volume < 30 else "🔉" if volume < 70 else "🔊"
        vol_widget.update(f"{icon} {volume}%")

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Formata tempo em MM:SS."""
        if seconds < 0:
            return "0:00"
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}"
