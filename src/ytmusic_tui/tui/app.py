"""Aplicação TUI principal usando Textual."""
import asyncio
import contextlib
import threading
import time
from pathlib import Path

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    DataTable,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from ytmusic_tui.api import ytmusic
from ytmusic_tui.config import settings
from ytmusic_tui.download import DownloadStatus, DownloadTask, download_manager
from ytmusic_tui.library import db_manager, library
from ytmusic_tui.library.models import Track
from ytmusic_tui.player import PlayerEvent, PlayerState, TrackInfo, player

# ===== Widgets Customizados =====

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

    def __init__(self, tracks: list[Track] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.tracks: list[Track] = []
        self.set_tracks(tracks or [])

    def set_tracks(self, tracks: list[Track]) -> None:
        """Atualiza a lista sem remontar o widget (evita ``DuplicateIds``).

        Os itens são recriados in-place; por isso não usam ``id``.
        """
        self.tracks = list(tracks)
        self.clear()
        for track in self.tracks:
            artists = ", ".join(track.artist_names)
            label = f"{track.title} — {artists}" if artists else track.title
            self.append(ListItem(Label(label, markup=False)))

    def get_selected_track(self) -> Track | None:
        """Retorna faixa selecionada."""
        if self.index is not None and 0 <= self.index < len(self.tracks):
            return self.tracks[self.index]
        return None


class SearchInput(Input):
    """Input de busca com placeholder."""
    def __init__(self, **kwargs):
        super().__init__(placeholder="🔍 Buscar músicas, artistas, álbuns...", **kwargs)


class SongListView(AutoHighlightListView):
    """Lista de resultados de busca (dicionários crus da API)."""

    def __init__(self, songs: list[dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.songs: list[dict] = []
        self.set_songs(songs or [])

    def set_songs(self, songs: list[dict]) -> None:
        """Atualiza os resultados exibidos (in-place, sem ``id`` nos itens)."""
        self.songs = list(songs)
        self.clear()
        for song in self.songs:
            artists = ", ".join(a.get("name", "") for a in (song.get("artists") or []))
            title = song.get("title", "?")
            label = f"{title} — {artists}" if artists else title
            duration = song.get("duration", "")
            if duration:
                label += f"  ({duration})"
            # markup=False: títulos reais contêm [colchetes] que o Rich
            # interpretaria como marcação (texto sumia ou quebrava).
            self.append(ListItem(Label(label, markup=False)))

    def get_selected_song(self) -> dict | None:
        """Retorna o dicionário da música selecionada."""
        if self.index is not None and 0 <= self.index < len(self.songs):
            return self.songs[self.index]
        return None


class AlbumListView(AutoHighlightListView):
    """Lista de álbuns (dicionários crus da API de busca)."""

    def __init__(self, albums: list[dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.albums: list[dict] = []
        self.set_albums(albums or [])

    def set_albums(self, albums: list[dict]) -> None:
        """Atualiza a lista exibida (in-place, sem ``id`` nos itens)."""
        self.albums = list(albums)
        self.clear()
        for album in self.albums:
            artists = ", ".join(
                a.get("name", "")
                for a in (album.get("artists") or [])
                if isinstance(a, dict)
            )
            title = album.get("title", "?")
            kind = album.get("type") or "Álbum"
            year = str(album.get("year") or "")
            label = f"💿 {title}"
            if artists:
                label += f" — {artists}"
            meta = ", ".join(part for part in (kind, year) if part)
            label += f"  ({meta})"
            # markup=False: títulos reais contêm [colchetes] que o Rich
            # interpretaria como marcação.
            self.append(ListItem(Label(label, markup=False)))

    def get_selected_album(self) -> dict | None:
        """Retorna o dicionário do álbum selecionado."""
        if self.index is not None and 0 <= self.index < len(self.albums):
            return self.albums[self.index]
        return None


def _album_artist_text(album: dict) -> str:
    """Nome(s) do(s) artista(s) de um álbum (item de busca ou get_album)."""
    artists = album.get("artists")
    if isinstance(artists, list):
        names = [a.get("name", "") for a in artists if isinstance(a, dict)]
        text = ", ".join(name for name in names if name)
        if text:
            return text
    return str(album.get("artist") or "")


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

    def __init__(self, *args, **kwargs):
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
        """Atualiza estado do botão play/pause."""
        btn = self.query_one("#btn-play-pause", Button)
        if state == PlayerState.PLAYING:
            btn.label = "⏸"
        else:
            btn.label = "▶"

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


# ===== Telas =====

class MainScreen(Screen):
    """Tela principal com abas."""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Sair"),
        Binding("ctrl+s", "search", "Buscar"),
        Binding("space", "play_pause", "Play/Pause"),
        Binding("right", "next", "Próxima"),
        Binding("left", "previous", "Anterior"),
        Binding("ctrl+d", "download", "Baixar", priority=True),
        Binding("l", "like", "Curtir"),
        Binding("a", "download_album", "Baixar álbum"),
        Binding("escape", "back_to_search", "Voltar", show=False),
        Binding("ctrl+l", "library", "Biblioteca"),
        Binding("f1", "help", "Ajuda"),
    ]

    def __init__(self):
        super().__init__()
        self._play_queue: list[TrackInfo] = []
        self._play_index: int = -1
        self._last_auto_next: float = 0.0
        # Álbum aberto na aba dedicada (dict do get_album); usado pelo "a".
        self._current_album: dict | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with TabbedContent(id="main-tabs"):
            with TabPane("🏠 Início", id="tab-home"):
                yield Static("[b]Bem-vindo ao YouTube Music TUI[/b]", classes="section-title")
                yield Static(
                    "Use Ctrl+S para buscar músicas e álbuns, ou Ctrl+L para ver sua biblioteca.\n"
                    "Enter num álbum abre a aba 💿 Álbum, onde 'a' baixa o álbum inteiro."
                )

            with TabPane("🔍 Busca", id="tab-search"):
                yield SearchInput(id="search-input")
                with Vertical(id="search-results"):
                    yield Static(
                        "Digite algo e pressione Enter para buscar.",
                        id="search-message",
                    )
                    yield Static("🎵 Músicas", id="search-songs-title", classes="list-title")
                    yield SongListView(id="search-songs")
                    yield Static("💿 Álbuns", id="search-albums-title", classes="list-title")
                    yield AlbumListView(id="search-albums")

            with TabPane("💿 Álbum", id="tab-album"):
                yield Static("💿 Nenhum álbum aberto", id="album-header", classes="section-title")
                with Vertical(id="album-body"):
                    yield Static(
                        "Busque um álbum na aba Busca e pressione Enter para abri-lo aqui.",
                        id="album-message",
                    )
                    yield Button(
                        "⬇ Baixar álbum inteiro (a)", id="btn-download-album", variant="primary"
                    )
                    yield SongListView(id="album-songs")

            with TabPane("📚 Biblioteca", id="tab-library"):
                yield Static("[b]📚 Biblioteca local[/b]", classes="section-title")
                with Vertical(id="library-body"):
                    yield Static(
                        "Nenhuma faixa na biblioteca local ainda.\n"
                        "Baixe músicas com Ctrl+D durante a reprodução.",
                        id="library-message",
                    )
                    yield TrackListView(id="library-list")

            with TabPane("📥 Downloads", id="tab-downloads"):
                yield Static("[b]Gerenciador de Downloads[/b]", classes="section-title")
                yield DataTable(id="downloads-table")

            with TabPane("⚙️ Config", id="tab-settings"):  # noqa: SIM117 (compose Textual)
                with Vertical(id="settings-content"):
                    yield Static("[b]Configurações[/b]", classes="section-title")
                    with Collapsible(title="Conta", collapsed=False):
                        yield Static(self._account_status_text(), id="account-status")
                        yield Static(
                            "Modo anônimo: busca, reprodução e download funcionam sem conta.\n"
                            "Curtidas são salvas apenas na biblioteca local.",
                            id="account-info",
                        )
                    with Collapsible(title="Player", collapsed=True):
                        yield Static("Volume padrão:")
                        yield Input(
                            value=str(settings.mpv_volume), id="setting-volume", type="integer"
                        )
                        yield Static("Qualidade de áudio:")
                        yield Select([
                            ("Baixa", "low"),
                            ("Média", "medium"),
                            ("Alta", "high"),
                            ("Melhor", "best"),
                        ], value=settings.mpv_audio_quality, id="setting-audio-quality")
                    with Collapsible(title="Downloads", collapsed=True):
                        yield Static("Diretório:")
                        yield Input(value=str(settings.download_dir), id="setting-download-dir")
                        yield Static("Formato:")
                        yield Select(
                            [("MP3", "mp3"), ("Opus", "opus"), ("M4A", "m4a"), ("FLAC", "flac")],
                            value=settings.download_format,
                            id="setting-format",
                        )
                        yield Static("Qualidade (kbps):")
                        yield Input(value=settings.download_quality, id="setting-download-quality")
                        yield Static("Downloads simultâneos:")
                        yield Input(
                            value=str(settings.download_concurrent),
                            id="setting-concurrent",
                            type="integer",
                        )
                    with Collapsible(title="Interface", collapsed=True):
                        yield Checkbox(
                            "Notificações",
                            value=settings.show_notifications,
                            id="setting-notifications",
                        )
                        yield Checkbox(
                            "Auto-play próxima",
                            value=settings.auto_play_next,
                            id="setting-autoplay",
                        )

        yield NowPlayingBar(id="now-playing")

    def _account_status_text(self) -> str:
        """Texto de status da conta (o app opera sem login)."""
        return "Status: [green]Modo anônimo (sem conta)[/green]"

    def on_mount(self) -> None:
        self.query_one("#search-songs", SongListView).display = False
        self.query_one("#search-songs-title", Static).display = False
        self.query_one("#search-albums", AlbumListView).display = False
        self.query_one("#search-albums-title", Static).display = False
        self.query_one("#album-songs", SongListView).display = False
        self.query_one("#btn-download-album", Button).display = False
        # A aba de álbum só aparece quando um álbum é aberto pela busca.
        self._set_album_tab_visible(False)
        self.refresh_library()
        self.update_downloads_table()

    def refresh_library(self) -> None:
        """Atualiza a lista de faixas da biblioteca local (in-place)."""
        try:
            view = self.query_one("#library-list", TrackListView)
            message = self.query_one("#library-message", Static)
        except Exception:
            return

        try:
            tracks = library.get_recent_tracks(limit=500)
        except Exception:
            tracks = []

        view.set_tracks(tracks)
        view.display = bool(tracks)
        message.display = not tracks

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Atualiza o conteúdo da aba ao ser ativada."""
        pane_id = getattr(event.pane, "id", None)
        if pane_id == "tab-library":
            self.refresh_library()
        elif pane_id == "tab-downloads":
            self.update_downloads_table()

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

    # ===== Álbuns =====

    def _album_tab(self):
        """Retorna o ``Tab`` da aba de álbum (None se ainda não montada)."""
        with contextlib.suppress(Exception):
            return self.query_one("#main-tabs", TabbedContent).get_tab("tab-album")
        return None

    def _set_album_tab_visible(self, visible: bool, title: str | None = None) -> None:
        """Mostra/oculta a aba de álbum e ajusta o rótulo com o nome."""
        tab = self._album_tab()
        if tab is None:
            return
        if visible:
            tab.remove_class("-hidden")
            if title:
                tab.label = f"💿 {title[:18]}"
        else:
            tab.add_class("-hidden")

    def _render_album_header(self, album: dict) -> None:
        """Título da aba de álbum: nome, artista, ano e nº de faixas."""
        try:
            header = self.query_one("#album-header", Static)
        except Exception:
            return
        title = album.get("title", "?")
        artist = _album_artist_text(album)
        year = str(album.get("year") or "")
        count = album.get("trackCount") or len(album.get("tracks") or [])
        parts = [part for part in (artist, year, f"{count} faixas" if count else "") if part]
        suffix = f" — {escape(' · '.join(parts))}" if parts else ""
        header.update(f"💿 [b]{escape(title)}[/b]{suffix}")

    def _render_album_message(self, text: str) -> None:
        """Mostra (ou oculta, com texto vazio) a mensagem da aba de álbum."""
        try:
            message = self.query_one("#album-message", Static)
        except Exception:
            return
        message.display = bool(text)
        if text:
            message.update(text)

    def open_album(self, browse_id: str, album_item: dict | None = None) -> None:
        """Abre o álbum na aba dedicada e carrega as faixas em background."""
        if not browse_id:
            self._toast("Álbum sem identificador; não é possível abrir")
            return
        if album_item:
            # Cabeçalho imediato com os dados da busca; o get_album completa.
            self._render_album_header(album_item)
        self._render_album_message("Carregando álbum...")
        self._set_album_tab_visible(True, (album_item or {}).get("title"))
        self._switch_tab("tab-album")
        # exclusive=True: abrir outro álbum cancela a carga anterior.
        self.run_worker(self._load_album(browse_id), group="album", exclusive=True)

    async def _load_album(self, browse_id: str) -> None:
        """Carrega os detalhes do álbum fora da thread da UI."""
        try:
            details = await asyncio.to_thread(ytmusic.get_album, browse_id)
        except Exception as e:
            # escape(): mensagens de erro podem conter [colchetes].
            self._render_album_message(f"Erro ao carregar álbum: {escape(str(e))}")
            return
        self.display_album(details)

    def display_album(self, album: dict) -> None:
        """Preenche a aba de álbum com cabeçalho e lista de faixas."""
        self._current_album = album
        tracks = [
            track
            for track in (album.get("tracks") or [])
            if track.get("videoId") and track.get("isAvailable", True)
        ]
        self._render_album_header(album)
        self._set_album_tab_visible(True, album.get("title") or "")
        try:
            view = self.query_one("#album-songs", SongListView)
            button = self.query_one("#btn-download-album", Button)
        except Exception:
            return
        view.set_songs(tracks)
        view.display = bool(tracks)
        button.display = bool(tracks)
        self._render_album_message("" if tracks else "Álbum sem faixas disponíveis.")
        if tracks:
            # Foco na lista: Enter toca, "a" baixa o álbum, setas navegam.
            self.call_after_refresh(view.focus)

    # ===== Ações =====

    def _switch_tab(self, tab_id: str) -> None:
        """Troca de aba de forma segura com o teclado.

        O ``TabbedContent`` reativa o painel de qualquer widget que receba
        foco programático (``TabPane.Focused``). Se a troca acontecer com o
        foco ainda dentro do painel antigo, o Textual transfere o foco para
        outro widget desse MESMO painel ao escondê-lo, o painel se reativa e
        a troca se desfaz. Remover o foco antes evita a regressão.
        """
        tabs = self.query_one("#main-tabs", TabbedContent)
        if tabs.active == tab_id:
            return
        with contextlib.suppress(Exception):
            self.set_focus(None)
        tabs.active = tab_id

    def action_search(self) -> None:
        """Foca no input de busca."""
        self._switch_tab("tab-search")
        # O painel pode ser exibido de forma assíncrona; foca depois.
        self.call_after_refresh(self._focus_search)

    def _focus_search(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#search-input", SearchInput).focus()

    def action_play_pause(self) -> None:
        """Alterna play/pause."""
        player.toggle_pause()

    def action_next(self) -> None:
        """Próxima faixa."""
        player.next_track()

    def action_previous(self) -> None:
        """Faixa anterior."""
        player.previous_track()

    def action_library(self) -> None:
        """Abre a aba da biblioteca local."""
        self._switch_tab("tab-library")
        self.refresh_library()

    def action_help(self) -> None:
        """Mostra os atalhos de teclado."""
        self._toast(
            "Ctrl+S buscar · Enter tocar/abrir álbum · Espaço play/pause · ←/→ anterior/próxima · "
            "Ctrl+D baixar faixa · a baixar álbum · Esc voltar · L curtir · Ctrl+L biblioteca · "
            "F1 ajuda · Ctrl+Q sair"
        )

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

    def action_back_to_search(self) -> None:
        """Esc na aba de álbum volta para a busca (pronto para digitar)."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        if tabs.active == "tab-album":
            self._switch_tab("tab-search")
            self.call_after_refresh(self._focus_search)

    def action_like(self) -> None:
        """Curte/descurte a faixa atual (apenas na biblioteca local, sem conta)."""
        track = player.current_track
        if not track or not track.video_id:
            self._toast("Nenhuma faixa em reprodução")
            return

        lib_track = library.get_track_by_source_id(track.video_id)
        if not lib_track:
            self._toast("Baixe a faixa primeiro (Ctrl+D) para curtí-la na biblioteca local")
            return
        liked = library.toggle_like(lib_track.id)
        self._toast("❤️ Curtida (local)" if liked else "Removida das curtidas (local)")

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

        parts = []
        if queued:
            parts.append(f"{queued} faixa(s) enfileirada(s)")
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

    def _toast(self, message: str) -> None:
        """Mostra uma notificação (respeitando settings.show_notifications)."""
        if settings.show_notifications:
            self.notify(message, timeout=4, markup=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Lida com os botões de controle do player e de download de álbum."""
        button_id = event.button.id
        if button_id == "btn-prev":
            player.previous_track()
        elif button_id == "btn-play-pause":
            player.toggle_pause()
        elif button_id == "btn-next":
            player.next_track()
        elif button_id == "btn-download-album":
            self.action_download_album()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            # perform_search é assíncrono: precisa ser agendado como worker
            self.run_worker(self.perform_search(event.value), exclusive=True, group="search")
            return
        self._apply_text_setting(event.input.id, event.value)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Aplica seleções da aba Config."""
        if event.select.id == "setting-audio-quality" and event.value:
            settings.update_and_save(mpv_audio_quality=str(event.value))
            player.apply_audio_quality()
            self._toast(f"Qualidade de áudio: {event.value} (aplica na próxima faixa)")
        elif event.select.id == "setting-format" and event.value:
            settings.update_and_save(download_format=str(event.value))
            self._toast(f"Formato de download: {event.value}")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Aplica checkboxes da aba Config."""
        if event.checkbox.id == "setting-notifications":
            settings.update_and_save(show_notifications=event.value)
        elif event.checkbox.id == "setting-autoplay":
            settings.update_and_save(auto_play_next=event.value)

    def _apply_text_setting(self, input_id: str, raw_value: str) -> None:
        """Aplica campos de texto da aba Config (Enter para confirmar)."""
        value = raw_value.strip()
        try:
            if input_id == "setting-volume":
                volume = max(0, min(100, int(value)))
                settings.update_and_save(mpv_volume=volume)
                player.set_volume(volume)
                self.query_one(NowPlayingBar).update_volume(volume)
                self._toast(f"Volume: {volume}%")
            elif input_id == "setting-download-dir":
                path = Path(value).expanduser()
                path.mkdir(parents=True, exist_ok=True)
                settings.update_and_save(download_dir=path)
                self._toast(f"Diretório de downloads: {path}")
            elif input_id == "setting-download-quality":
                settings.update_and_save(download_quality=value or "320")
                self._toast(f"Qualidade do download: {value or '320'}")
            elif input_id == "setting-concurrent":
                concurrent = max(1, min(10, int(value)))
                settings.update_and_save(download_concurrent=concurrent)
                download_manager.set_concurrent(concurrent)
                self._toast(f"Downloads simultâneos: {concurrent}")
        except (TypeError, ValueError):
            self._toast("Valor inválido")
        except OSError as exc:
            self._toast(f"Não foi possível usar o diretório: {exc}")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Reproduz o item selecionado (ou abre o álbum) em uma lista."""
        view = event.list_view
        if view.id == "search-songs":
            song = view.get_selected_song()
            if song:
                self.play_song(song)
        elif view.id == "search-albums":
            album = view.get_selected_album()
            if album:
                self.open_album(album.get("browseId", ""), album)
        elif view.id == "album-songs":
            song = view.get_selected_song()
            if song:
                self.play_song(song, view_id="album-songs")
        elif view.id == "library-list":
            track = view.get_selected_track()
            if track:
                self.play_library_track(track)

    # ===== Reprodução =====

    @staticmethod
    def _track_info_from_song(song: dict) -> TrackInfo:
        """Converte um resultado de busca (ou faixa de álbum) em TrackInfo."""
        artists = ", ".join(a.get("name", "") for a in (song.get("artists") or []))
        album = ""
        album_data = song.get("album")
        if isinstance(album_data, dict):
            album = album_data.get("name", "")
        elif isinstance(album_data, str):
            # Faixas de get_album trazem o nome do álbum como string.
            album = album_data
        thumbnails = song.get("thumbnails") or []
        thumbnail = thumbnails[-1].get("url", "") if thumbnails else ""
        video_id = song.get("videoId", "")
        return TrackInfo(
            video_id=video_id,
            title=song.get("title", ""),
            artist=artists,
            album=album,
            duration=float(song.get("duration_seconds") or 0),
            thumbnail_url=thumbnail,
            source_url=f"https://music.youtube.com/watch?v={video_id}",
        )

    @staticmethod
    def _track_info_from_library(track: Track) -> TrackInfo:
        """Converte uma faixa da biblioteca em TrackInfo."""
        if track.is_downloaded and track.local_path:
            source_url = str(track.local_path)
        else:
            source_url = f"https://music.youtube.com/watch?v={track.source_id}"
        return TrackInfo(
            video_id=track.source_id,
            title=track.title,
            artist=", ".join(track.artist_names),
            album=track.album.title if track.album else "",
            source_url=source_url,
        )

    def play_song(self, song: dict, view_id: str = "search-songs") -> None:
        """Reproduz uma música vinda da API (resultado de busca ou álbum)."""
        info = self._track_info_from_song(song)
        if not info.video_id:
            self._toast("Faixa sem videoId; não é possível reproduzir")
            return

        view = self.query_one(f"#{view_id}", SongListView)
        index = view.index if view.index is not None else 0
        self._play_queue = [self._track_info_from_song(s) for s in view.songs]
        self._play_index = index if 0 <= index < len(self._play_queue) else 0
        self._start_playback(info)

    def play_library_track(self, track: Track) -> None:
        """Reproduz uma faixa da biblioteca local."""
        view = self.query_one("#library-list", TrackListView)
        index = view.index if view.index is not None else 0
        self._play_queue = [self._track_info_from_library(t) for t in view.tracks]
        self._play_index = index if 0 <= index < len(self._play_queue) else 0
        self._start_playback(self._track_info_from_library(track))

    def _start_playback(self, info: TrackInfo) -> None:
        """Inicia a reprodução de uma faixa."""
        if player.play(info):
            self._toast(f"▶ {info.title}")

    def _play_relative(self, delta: int) -> bool:
        """Toca a faixa na posição atual + delta (fila da última lista usada)."""
        new_index = self._play_index + delta
        if not (0 <= new_index < len(self._play_queue)):
            return False
        self._play_index = new_index
        self._start_playback(self._play_queue[new_index])
        return True

    def _maybe_auto_next(self) -> bool:
        """Avança para a próxima faixa (auto-play), com debounce.

        O fim da faixa gera dois eventos ("track_ended" e "ended"); o
        debounce evita avançar duas vezes.
        """
        if not settings.auto_play_next:
            return False
        now = time.monotonic()
        if now - self._last_auto_next < 1.0:
            return False
        if self._play_index + 1 >= len(self._play_queue):
            return False
        self._last_auto_next = now
        return self._play_relative(1)

    # ===== Busca =====

    async def perform_search(self, query: str) -> None:
        """Executa busca de músicas e álbuns."""
        if not query.strip():
            return

        if not ytmusic.initialize():
            self._render_search_message("Não foi possível inicializar a busca.")
            return

        self._render_search_message("Buscando...")

        try:
            # search_catalog: músicas + álbuns em 2 requisições paralelas
            # (~2s no total, a mesma latência de uma busca só). A busca sem
            # filtro faria 1 requisição, mas caparia as músicas em ~5 itens.
            results = await asyncio.to_thread(ytmusic.search_catalog, query)
            self.display_search_results(results)
        except Exception as e:
            # escape(): mensagens de erro podem conter [colchetes].
            self._render_search_message(f"Erro na busca: {escape(str(e))}")

    def _render_search_message(self, text: str) -> None:
        """Mostra uma mensagem no lugar dos resultados (in-place)."""
        try:
            message = self.query_one("#search-message", Static)
            hidden = [
                self.query_one("#search-songs", SongListView),
                self.query_one("#search-songs-title", Static),
                self.query_one("#search-albums", AlbumListView),
                self.query_one("#search-albums-title", Static),
            ]
        except Exception:
            return
        for widget in hidden:
            widget.display = False
        message.display = True
        message.update(text)

    def display_search_results(self, results) -> None:
        """Exibe resultados da busca: músicas e álbuns (in-place).

        Aceita uma lista de músicas (compatibilidade) ou um ``SearchResult``.
        """
        if isinstance(results, list):
            tracks, albums = list(results), []
        else:
            tracks = list(getattr(results, "tracks", []) or [])
            albums = list(getattr(results, "albums", []) or [])
        tracks = [song for song in tracks if song.get("videoId")]
        albums = [album for album in albums if album.get("browseId")]
        if not tracks and not albums:
            self._render_search_message("Nenhum resultado encontrado.")
            return

        try:
            songs_view = self.query_one("#search-songs", SongListView)
            songs_title = self.query_one("#search-songs-title", Static)
            albums_view = self.query_one("#search-albums", AlbumListView)
            albums_title = self.query_one("#search-albums-title", Static)
            message = self.query_one("#search-message", Static)
        except Exception:
            return

        songs_view.set_songs(tracks[:25])
        albums_view.set_albums(albums[:15])
        message.display = False
        # Cada seção aparece apenas quando tem itens; as alturas em `fr`
        # fazem a lista de músicas ocupar todo o espaço quando não há álbuns.
        songs_view.display = songs_title.display = bool(tracks)
        albums_view.display = albums_title.display = bool(albums)


class YTMusicTUI(App):
    """Aplicação principal."""

    TITLE = "YouTube Music TUI"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Sair", show=True),
        Binding("f1", "help", "Ajuda", show=True),
    ]

    def __init__(self):
        super().__init__()
        self._ui_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        # Nada a compor: as telas são instaladas em on_mount. Retornar uma
        # `Screen` aqui a tornaria filha da tela padrão, e não a tela ativa.
        return
        yield  # pragma: no cover

    def on_mount(self) -> None:
        """Inicialização após montagem."""
        # Inicializar banco de dados
        db_manager.create_all()

        # Inicializar API (cliente anônimo; nenhum login necessário)
        ytmusic.initialize()

        # Configurar callbacks do player
        player.on_event(self._on_player_event)

        # Timer único da UI: a tabela de downloads muda sem gerar eventos;
        # a barra de reprodução é atualizada por eventos do player.
        self._ui_timer = self.set_interval(0.5, self._refresh_downloads_ui)

        # Instalar a tela principal
        self.push_screen(MainScreen())

    def _on_player_event(self, event: PlayerEvent) -> None:
        """Callback de eventos do player (pode vir da thread do libmpv)."""
        if threading.current_thread() is threading.main_thread():
            self._handle_player_event(event)
            return
        # Observers/eventos do mpv rodam na thread de eventos do libmpv;
        # widgets do Textual só podem ser tocados na thread principal.
        with contextlib.suppress(Exception):  # app encerrando
            self.call_from_thread(self._handle_player_event, event)

    def _handle_player_event(self, event: PlayerEvent) -> None:
        """Atualiza a UI em resposta a um evento do player."""
        screen = self.screen
        if not isinstance(screen, MainScreen):
            return
        try:
            np_bar = screen.query_one("#now-playing", NowPlayingBar)
        except Exception:
            return

        name = event.event
        if name == "play":
            np_bar.update_track(event.data.get("track", TrackInfo()))
            np_bar.update_state(PlayerState.PLAYING)
            np_bar.update_volume(player.get_volume())
        elif name == "pause":
            np_bar.update_state(PlayerState.PAUSED)
        elif name == "resume":
            np_bar.update_state(PlayerState.PLAYING)
        elif name == "stop":
            np_bar.update_track(TrackInfo())
            np_bar.update_state(PlayerState.STOPPED)
        elif name == "ended":
            # Se o auto-play já iniciou outra faixa, não limpar a barra.
            if player.current_track is None:
                np_bar.update_track(TrackInfo())
                np_bar.update_state(PlayerState.STOPPED)
        elif name == "track_ended":
            screen._maybe_auto_next()
        elif name == "next":
            screen._play_relative(1)
        elif name == "previous":
            screen._play_relative(-1)
        elif name == "position":
            np_bar.update_position(
                event.data.get("position", 0),
                event.data.get("duration", 0),
            )
        elif name == "error":
            np_bar.update_state(PlayerState.ERROR)
            screen._toast(f"Erro no player: {event.data.get('message', '')}")

    def _refresh_downloads_ui(self) -> None:
        """Atualiza a tabela de downloads (somente quando a aba está ativa)."""
        screen = self.screen
        if not isinstance(screen, MainScreen):
            return
        try:
            tabs = screen.query_one("#main-tabs", TabbedContent)
            if tabs.active == "tab-downloads":
                screen.update_downloads_table()
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Limpeza ao sair."""
        if self._ui_timer:
            self._ui_timer.stop()
        player.shutdown()
        download_manager.shutdown()
        db_manager.close()


def main():
    """Ponto de entrada principal."""
    app = YTMusicTUI()
    app.run()


if __name__ == "__main__":
    main()