"""Mascaramento de diagnóstico para exibição ao usuário (§8.3/T06).

Erros de terceiros (yt-dlp, mpv, sqlite) trazem caminho absoluto do usuário
e URL assinada com token de sessão. O **log** preserva o detalhe cru — ele
fica na máquina do usuário; a **TUI** (toast, tabela, estado de erro) e
qualquer relatório não: ``mask_diagnostics`` troca o HOME literal por ``~``
e remove query, fragment e credenciais das URLs http(s).

O que NÃO é mascarado de propósito: caminhos fora do HOME (ex.: mídia em
outro ponto de montagem) e nomes de arquivo do próprio usuário — são dados
dele, e esconder tudo tornaria a mensagem inútil.
"""

import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

__all__ = ["mask_diagnostics", "mask_home", "mask_urls"]

#: URL http(s) dentro de texto livre; exclui aspas/parênteses que costumam
#: delimitar o link numa mensagem (``url=https://… (caused by …)``).
_URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]]+", re.IGNORECASE)

#: Pontuação final que pertence ao texto, não à URL.
_URL_TAIL_CHARS = ".,;:!?"


def mask_home(text: str) -> str:
    """Troca o caminho do HOME (literal) por ``~``."""
    home = str(Path.home())
    if len(home) > 1:
        text = text.replace(home, "~")
    return text


def _mask_one_url(match: re.Match[str]) -> str:
    """Devolve a URL sem userinfo/query/fragment (``?…`` marca o corte)."""
    raw = match.group(0)
    tail = ""
    while raw and raw[-1] in _URL_TAIL_CHARS:
        tail = raw[-1] + tail
        raw = raw[:-1]
    try:
        parts = urlsplit(raw)
    except ValueError:
        return match.group(0)
    netloc = parts.netloc.split("@", 1)[1] if "@" in parts.netloc else parts.netloc
    sanitized = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    if parts.query or parts.fragment:
        sanitized += "?…"
    return sanitized + tail


def mask_urls(text: str) -> str:
    """Remove query/fragment/credenciais de URLs http(s) do texto."""
    return _URL_RE.sub(_mask_one_url, text)


def mask_diagnostics(text: str) -> str:
    """Aplica todo o mascaramento de exibição (HOME + URLs)."""
    return mask_urls(mask_home(text))
