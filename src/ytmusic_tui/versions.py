"""Diagnóstico de versões das dependências críticas (T10-R5).

O app informa a versão INSTALADA × TESTADA de ``ytmusicapi`` e ``yt-dlp`` e
orienta atualizar quando apropriado (a aba ⚙️ Config mostra o bloco). A
"testada" é a versão que o ``uv.lock`` instala no CI (``uv sync --locked``):
um teste unitário amarra as duas pontas — subir o lock (Dependabot) sem
confirmar a versão aqui deixa o CI vermelho até alguém atualizar a constante
(o "testado" é uma afirmação, não um chute).

Comparação por tupla numérica simples, sem dependência nova: sufixos não
numéricos (``rc1``, ``.dev0``) são ignorados — o objetivo é orientar o
usuário, não resolver semver.
"""

import importlib.metadata
import platform
from dataclasses import dataclass

from ytmusic_tui import __version__

__all__ = [
    "DEPENDENCIES",
    "TESTED_YT_DLP",
    "TESTED_YTMUSICAPI",
    "DependencyStatus",
    "check_dependencies",
    "parse_version",
    "render_dependencies",
    "status_for",
    "versions_summary",
]

#: Versões validadas pela suíte/CI (as do ``uv.lock``).
TESTED_YTMUSICAPI = "1.12.3"
TESTED_YT_DLP = "2026.8.19"

#: Dependências externas cuja versão muda o comportamento do app.
DEPENDENCIES: dict[str, str] = {
    "ytmusicapi": TESTED_YTMUSICAPI,
    "yt-dlp": TESTED_YT_DLP,
}


def parse_version(text: str) -> tuple[int, ...]:
    """Tupla numérica da versão (sufixos não numéricos são ignorados)."""
    parts: list[int] = []
    for chunk in text.split("."):
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    """Estado de uma dependência externa: instalada × testada."""

    name: str
    installed: str | None
    tested: str
    state: str  # "ok" | "newer" | "older" | "missing"

    @property
    def needs_update(self) -> bool:
        """A orientação de atualizar se aplica? (mais velha ou ausente)"""
        return self.state in {"older", "missing"}

    def describe(self) -> str:
        """Linha curta para a UI (versões não são sensíveis; sem mascarar)."""
        if self.state == "missing":
            return f"{self.name}: não instalada (testada: {self.tested}) — reinstale o app"
        if self.state == "older":
            return (
                f"{self.name} {self.installed} é mais velha que a testada "
                f"({self.tested}) — atualize (uv sync ou reinstale o app)"
            )
        if self.state == "newer":
            return (
                f"{self.name} {self.installed} é mais nova que a testada "
                f"({self.tested}) — atualize o app se algo falhar"
            )
        return f"{self.name} {self.installed} (testada: {self.tested})"


def status_for(name: str, tested: str, installed: str | None) -> DependencyStatus:
    """Compara a versão instalada com a testada (puro, testável)."""
    if not installed:
        return DependencyStatus(name, None, tested, "missing")
    current, reference = parse_version(installed), parse_version(tested)
    if current == reference:
        state = "ok"
    elif current > reference:
        state = "newer"
    else:
        state = "older"
    return DependencyStatus(name, installed, tested, state)


def check_dependencies() -> list[DependencyStatus]:
    """Estado das dependências externas no ambiente em execução."""
    statuses: list[DependencyStatus] = []
    for name, tested in DEPENDENCIES.items():
        try:
            installed: str | None = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        statuses.append(status_for(name, tested, installed))
    return statuses


def render_dependencies() -> str:
    """Bloco curto para a aba Config (uma linha por dependência)."""
    return "\n".join(status.describe() for status in check_dependencies())


def versions_summary() -> str:
    """Linha única com app, Python e as dependências externas (T13).

    Usada pelos eventos ``app_start``/``app_stop`` (§13.1) e pelo cabeçalho
    do ``doctor`` — um lugar só para o formato.
    """
    installed = {status.name: (status.installed or "ausente") for status in check_dependencies()}
    return (
        f"app v{__version__} · Python {platform.python_version()} · "
        f"ytmusicapi {installed.get('ytmusicapi', 'ausente')} · "
        f"yt-dlp {installed.get('yt-dlp', 'ausente')}"
    )
