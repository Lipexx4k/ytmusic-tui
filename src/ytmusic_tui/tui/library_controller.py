"""Aba 📚 da biblioteca local (mixin de ``MainScreen``)."""

import logging

from rich.markup import escape
from textual.widgets import Static

from ytmusic_tui.library import library
from ytmusic_tui.log import log_file_path
from ytmusic_tui.player import player
from ytmusic_tui.tui.widgets import TrackListView

logger = logging.getLogger(__name__)

# Texto padrão da aba Biblioteca quando não há faixas carregadas (usado
# também para restaurá-lo depois de uma falha de carregamento).
LIBRARY_EMPTY_TEXT = (
    "Nenhuma faixa na biblioteca local ainda.\nBaixe músicas com Ctrl+D durante a reprodução."
)


class LibraryController:
    """Mixin com a listagem da biblioteca local e as curtidas."""

    def refresh_library(self) -> None:
        """Atualiza a lista de faixas da biblioteca local (in-place).

        Uma falha ao consultar o banco NÃO pode parecer uma biblioteca
        vazia: o usuário acharia que perdeu as faixas baixadas. O erro é
        registrado no log e mostrado na própria aba.
        """
        try:
            view = self.query_one("#library-list", TrackListView)
            message = self.query_one("#library-message", Static)
        except Exception:
            return

        try:
            tracks = library.get_recent_tracks(limit=500)
        except Exception as error:
            logger.exception("Falha ao carregar a biblioteca local")
            view.set_tracks([])
            view.display = False
            message.update(
                "[b]⚠️ Não foi possível carregar a biblioteca local[/b]\n"
                f"{escape(str(error))}\n"
                f"Nada foi apagado. Detalhes no log: {escape(str(log_file_path()))}"
            )
            message.display = True
            self._toast("⚠️ Falha ao carregar a biblioteca local — detalhes no log")
            return

        view.set_tracks(tracks)
        view.display = bool(tracks)
        message.display = not tracks
        message.update(LIBRARY_EMPTY_TEXT)

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
