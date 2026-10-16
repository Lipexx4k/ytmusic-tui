"""Telas modais da TUI: Ajuda (T12-R1)."""

from collections.abc import Iterable

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from ytmusic_tui.tui.messages import (
    HELP_FOOTER,
    HELP_KEYS_TITLE,
    HELP_NAV_LINES,
    HELP_NAV_TITLE,
    HELP_TITLE,
    help_shortcut_lines,
)


class HelpScreen(ModalScreen[None]):
    """Ajuda modal com navegação e atalhos reais (F1 abre, Esc fecha).

    O conteúdo dos atalhos é montado a partir de ``App.BINDINGS +
    MainScreen.BINDINGS`` no momento de abrir — a ajuda não guarda uma
    cópia própria da lista (era o toast com texto duplicado que ficava
    desatualizado).
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Fechar"),
        Binding("f1", "dismiss", "Fechar"),
    ]

    def __init__(self, bindings: Iterable[BindingType]) -> None:
        super().__init__()
        self._help_bindings: list[BindingType] = list(bindings)

    def compose(self) -> ComposeResult:
        lines = [
            f"[b]{HELP_TITLE}[/b]",
            "",
            f"[b]{HELP_NAV_TITLE}[/b]",
            *HELP_NAV_LINES,
            "",
            f"[b]{HELP_KEYS_TITLE}[/b]",
            *help_shortcut_lines(self._help_bindings),
            "",
            HELP_FOOTER,
        ]
        with Vertical(id="help-box"):
            yield Static("\n".join(lines), id="help-content", markup=True)
