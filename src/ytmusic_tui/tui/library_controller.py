"""Aba 📚 da biblioteca local (mixin de ``MainScreen``)."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from rich.markup import escape
from textual.widgets import Static

from ytmusic_tui.library import library
from ytmusic_tui.library.errors import LibraryError, describe_library_error
from ytmusic_tui.library.recovery import reconcile
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

    # Membros fornecidos pela tela host (o mypy analisa cada mixin
    # isoladamente; as declarações abaixo existem só na checagem de tipos).
    if TYPE_CHECKING:

        def query_one(self, selector: Any, expect_type: Any = None) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...
        def _toast(self, message: str) -> None: ...

    def refresh_library(self) -> None:
        """Atualiza a lista de faixas da biblioteca local (in-place).

        Uma falha ao consultar o banco NÃO pode parecer uma biblioteca
        vazia: o usuário acharia que perdeu as faixas baixadas. O erro é
        registrado no log e mostrado na própria aba — com a mensagem
        específica do caso quando é tipado (T05-R4); falha na abertura do
        banco na inicialização também aparece aqui.
        """
        try:
            view = self.query_one("#library-list", TrackListView)
            message = self.query_one("#library-message", Static)
        except Exception:
            return

        startup_error = self._startup_db_error()
        if startup_error is not None:
            self._show_library_unavailable(view, message, describe_library_error(startup_error))
            return

        try:
            tracks = library.get_recent_tracks(limit=500)
        except LibraryError as error:
            logger.exception("Falha ao carregar a biblioteca local")
            self._show_library_unavailable(view, message, describe_library_error(error))
            return
        except Exception as error:
            logger.exception("Falha ao carregar a biblioteca local")
            self._show_library_unavailable(view, message, str(error))
            return

        view.set_tracks(tracks)
        view.display = bool(tracks)
        message.display = not tracks
        message.update(LIBRARY_EMPTY_TEXT)

    def _startup_db_error(self) -> LibraryError | None:
        """Erro tipado da abertura do banco na app (None = tudo certo).

        Lido por ``getattr`` porque o mixin não herda de ``Screen``: o
        membro é da classe host (``YTMusicTUI``), e importar o tipo dela
        aqui criaria ciclo (app → screens → controllers).
        """
        app = getattr(self, "app", None)
        return cast("LibraryError | None", getattr(app, "db_error", None))

    def _show_library_unavailable(self, view: TrackListView, message: Static, reason: str) -> None:
        """Mostra o motivo exato da falha (nunca uma lista "vazia") + o log."""
        view.set_tracks([])
        view.display = False
        message.update(
            "[b]⚠️ Não foi possível carregar a biblioteca local[/b]\n"
            f"{escape(reason)}\n"
            f"Nada foi apagado. Detalhes no log: {escape(str(log_file_path()))}"
        )
        message.display = True
        self._toast("⚠️ Falha ao carregar a biblioteca local — detalhes no log")

    # ===== Reconciliação de arquivos (§5.3/T03) =====

    def start_reconciliation(self) -> None:
        """Dispara a reconciliação de arquivos no início da sessão (§5.3).

        Roda num worker porque a varredura de disco pode ser lenta (INV-12):
        a UI não espera. Achados viram toast + atualização da biblioteca;
        detalhes ficam no log.
        """
        self.run_worker(self._run_reconciliation(), group="reconcile")

    async def _run_reconciliation(self) -> None:
        """Executa a varredura fora do loop e resume o resultado na UI."""
        try:
            report = await asyncio.to_thread(reconcile)
        except Exception:
            # Falha na reconciliação não apaga nada; fica registrada no log.
            logger.exception("Falha na reconciliação de arquivos")
            return
        if report.has_findings:
            self._toast(f"🧹 Reconciliação: {report.summary()}")
            self.refresh_library()

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
        liked = library.toggle_like(cast(int, lib_track.id))
        self._toast("❤️ Curtida (local)" if liked else "Removida das curtidas (local)")
