"""Strings e formatação de mensagens da TUI (T12-R7: ponto único, pt-BR).

As mensagens visíveis ao usuário — ajuda, erros, hints e toasts — nascem
aqui; telas e controllers importam daqui. Sem framework de i18n: o objetivo
é ter **um** lugar para ajustar texto, não tradução em tempo real.
"""

from collections.abc import Iterable

from textual.binding import Binding, BindingType

# ===== Ajuda (T12-R1) =====

HELP_TITLE = "❓ Ajuda — YouTube Music TUI"
HELP_NAV_TITLE = "Navegação"
HELP_NAV_LINES = (
    "↑/↓    navegar pelas listas",
    "Tab    alternar o foco entre os controles",
    "Enter  tocar a faixa / abrir o álbum selecionado",
    "Esc    voltar (da aba Álbum para a Busca)",
)
HELP_KEYS_TITLE = "Atalhos"
HELP_FOOTER = "Esc ou F1 fecha esta ajuda."

#: Nota por ação exibida ao lado do atalho na ajuda — espelha o
#: ``check_action`` de ``MainScreen`` (r/d só valem na aba 📥 Downloads).
HELP_NOTES: dict[str, str] = {
    "retry_download": "aba 📥 Downloads",
    "discard_download": "aba 📥 Downloads",
}

#: Nomes amigáveis das teclas na ajuda (chaves de ``Binding.key``).
_KEY_NAMES = {
    "space": "Espaço",
    "left": "←",
    "right": "→",
    "up": "↑",
    "down": "↓",
    "enter": "Enter",
    "escape": "Esc",
    "tab": "Tab",
    "backspace": "Backspace",
    "delete": "Delete",
}


def format_key(key: str) -> str:
    """Formata a tecla de um ``Binding`` para exibição (``ctrl+q`` → ``Ctrl+Q``)."""
    parts = []
    for part in key.split("+"):
        if part in _KEY_NAMES:
            token = _KEY_NAMES[part]
        elif len(part) == 1 or (part.startswith("f") and part[1:].isdigit()):
            token = part.upper()
        else:
            token = part.capitalize()
        parts.append(token)
    return "+".join(parts)


def _as_binding(entry: BindingType) -> Binding:
    """Normaliza uma entrada de ``BINDINGS`` (o Textual aceita tuplas também)."""
    if isinstance(entry, Binding):
        return entry
    return Binding(*entry)


def help_shortcut_lines(bindings: Iterable[BindingType]) -> list[str]:
    """Linhas de atalhos da ajuda, sem duplicar tecla (a 1ª ocorrência vale).

    Recebe ``App.BINDINGS + MainScreen.BINDINGS`` na ordem de exibição; a
    descrição vem do próprio binding (fonte única), com a nota por ação
    quando houver (ex.: r/d restritos à aba 📥 Downloads).
    """
    seen: set[str] = set()
    lines: list[str] = []
    for entry in bindings:
        binding = _as_binding(entry)
        if binding.key in seen:
            continue
        seen.add(binding.key)
        note = HELP_NOTES.get(binding.action)
        suffix = f"  [dim]({note})[/dim]" if note else ""
        lines.append(f"  [b]{format_key(binding.key):<8}[/b] {binding.description}{suffix}")
    return lines


# ===== Confirmação de descarte (T12-R4) =====

CONFIRM_DISCARD_TITLE = "Descartar download"
CONFIRM_DISCARD_HINT = "y/Enter confirma · n/Esc cancela"
CONFIRM_DISCARD_CANCELLED = "Descarte cancelado"


def confirm_discard_message(title: str) -> str:
    """Texto do modal de descarte (tecla d) — o que será removido e o que não."""
    return (
        f"{CONFIRM_DISCARD_TITLE}: {title}\n\n"
        "Os arquivos parciais desta tarefa serão removidos; o arquivo final já\n"
        "publicado (se existir) e a biblioteca não são tocados.\n\n"
        f"{CONFIRM_DISCARD_HINT}"
    )
