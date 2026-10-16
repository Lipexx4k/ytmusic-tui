"""Erros transversais da aplicação (T06 · §8.3).

Vive fora de ``config`` para que ``permissions`` e ``config`` possam usá-lo
sem ciclo de import. A entrada do app (``main``) traduz ``ConfigError`` em
mensagem amigável — falha de ambiente nunca vira traceback para o usuário.
"""

__all__ = ["ConfigError"]


class ConfigError(Exception):
    """Falha de configuração/ambiente (diretório, permissão, layout)."""
