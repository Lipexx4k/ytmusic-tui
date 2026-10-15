"""Aplicação TUI principal usando Textual.

A estrutura da TUI é dividida em módulos:

- ``widgets.py``: widgets personalizados;
- ``screens.py``: ``MainScreen`` (layout, atalhos e navegação);
- ``playback_controller.py``, ``download_controller.py`` e
  ``library_controller.py``: mixins de comportamento da tela principal.

Este módulo fica com a classe ``YTMusicTUI`` (ciclo de vida do app) e o
ponto de entrada ``main()``.
"""

import contextlib
import logging
import threading

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import TabbedContent

from ytmusic_tui.api import ytmusic
from ytmusic_tui.download import download_manager
from ytmusic_tui.library import db_manager
from ytmusic_tui.log import setup_logging
from ytmusic_tui.player import PlayerEvent, PlayerState, TrackInfo, player
from ytmusic_tui.tui.screens import MainScreen
from ytmusic_tui.tui.widgets import NowPlayingBar


class YTMusicTUI(App):
    """Aplicação principal."""

    TITLE = "YouTube Music TUI"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Sair", show=True),
        Binding("f1", "help", "Ajuda", show=True),
    ]

    def __init__(self) -> None:
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


def main() -> None:
    """Ponto de entrada principal."""
    try:
        setup_logging()
    except OSError:
        # Sem permissão para gravar o log, o app segue funcionando; o
        # NullHandler evita que mensagens caiam no stderr e sujem a TUI.
        logging.getLogger("ytmusic_tui").addHandler(logging.NullHandler())
    app = YTMusicTUI()
    app.run()


if __name__ == "__main__":
    main()
