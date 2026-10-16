"""Tela principal da TUI: abas, atalhos e navegação."""

import asyncio
import contextlib
from pathlib import Path
from typing import Any, cast

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    DataTable,
    Header,
    Input,
    ListView,
    Select,
    Static,
    Tab,
    TabbedContent,
    TabPane,
)

from ytmusic_tui.api import SearchResult, ytmusic
from ytmusic_tui.config import settings
from ytmusic_tui.diagnostics import mask_diagnostics
from ytmusic_tui.download import download_manager
from ytmusic_tui.player import TrackInfo, player
from ytmusic_tui.tui.download_controller import DownloadController
from ytmusic_tui.tui.library_controller import LIBRARY_EMPTY_TEXT, LibraryController
from ytmusic_tui.tui.playback_controller import PlaybackController
from ytmusic_tui.tui.widgets import (
    AlbumListView,
    NowPlayingBar,
    SearchInput,
    SongListView,
    TrackListView,
)


def _album_artist_text(album: dict) -> str:
    """Nome(s) do(s) artista(s) de um álbum (item de busca ou get_album)."""
    artists = album.get("artists")
    if isinstance(artists, list):
        names = [a.get("name", "") for a in artists if isinstance(a, dict)]
        text = ", ".join(name for name in names if name)
        if text:
            return text
    return str(album.get("artist") or "")


class MainScreen(PlaybackController, DownloadController, LibraryController, Screen):
    """Tela principal com abas.

    O comportamento é composto pelos mixins de controller — reprodução
    (:class:`PlaybackController`), downloads (:class:`DownloadController`)
    e biblioteca (:class:`LibraryController`); aqui ficam o layout, os
    atalhos e a navegação entre abas.
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Sair"),
        Binding("ctrl+s", "search", "Buscar"),
        Binding("space", "play_pause", "Play/Pause"),
        Binding("right", "next", "Próxima"),
        Binding("left", "previous", "Anterior"),
        Binding("ctrl+d", "download", "Baixar", priority=True),
        Binding("l", "like", "Curtir"),
        Binding("a", "download_album", "Baixar álbum"),
        Binding("r", "retry_download", "Retomar download"),
        Binding("d", "discard_download", "Descartar download"),
        Binding("escape", "back_to_search", "Voltar", show=False),
        Binding("ctrl+l", "library", "Biblioteca"),
        Binding("f1", "help", "Ajuda"),
    ]

    def __init__(self) -> None:
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
                    yield Static(LIBRARY_EMPTY_TEXT, id="library-message")
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
                        yield Select(
                            [
                                ("Baixa", "low"),
                                ("Média", "medium"),
                                ("Alta", "high"),
                                ("Melhor", "best"),
                            ],
                            value=settings.mpv_audio_quality,
                            id="setting-audio-quality",
                        )
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
        # Tarefas interrompidas recuperadas na inicialização (T04-R2): avisa
        # uma vez que há decisão pendente (r retoma, d descarta).
        self.announce_interrupted()
        # Reconciliação de arquivos/temporários (§5.3/T03), fora do loop:
        # avisa por toast só quando há o que reportar.
        self.start_reconciliation()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Atualiza o conteúdo da aba ao ser ativada."""
        pane_id = getattr(event.pane, "id", None)
        if pane_id == "tab-library":
            self.refresh_library()
        elif pane_id == "tab-downloads":
            self.update_downloads_table()

    # ===== Álbuns =====

    def _album_tab(self) -> Tab | None:
        """Retorna o ``Tab`` da aba de álbum (None se ainda não montada)."""
        with contextlib.suppress(Exception):
            tabs = self.query_one("#main-tabs", TabbedContent)
            return cast(Tab | None, tabs.get_tab("tab-album"))
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

    # ===== Navegação e ações gerais =====

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

    def action_back_to_search(self) -> None:
        """Esc na aba de álbum volta para a busca (pronto para digitar)."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        if tabs.active == "tab-album":
            self._switch_tab("tab-search")
            self.call_after_refresh(self._focus_search)

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
        if event.input.id is None:
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
            # §8.3/T06: erro do sistema traz caminho absoluto — exibe mascarado.
            self._toast(f"Não foi possível usar o diretório: {mask_diagnostics(str(exc))}")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Reproduz o item selecionado (ou abre o álbum) em uma lista."""
        view = event.list_view
        if isinstance(view, SongListView):
            song = view.get_selected_song()
            if song and view.id:
                self.play_song(song, view_id=view.id)
        elif isinstance(view, AlbumListView):
            album = view.get_selected_album()
            if album:
                self.open_album(album.get("browseId", ""), album)
        elif isinstance(view, TrackListView):
            track = view.get_selected_track()
            if track:
                self.play_library_track(track)

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

    def display_search_results(self, results: SearchResult | list[dict[str, Any]]) -> None:
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
