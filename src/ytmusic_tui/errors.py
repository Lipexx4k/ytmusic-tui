"""Erros transversais da aplicação (T06 · §8.3).

Vive fora de ``config`` para que ``permissions`` e ``config`` possam usá-lo
sem ciclo de import. A entrada do app (``main``) traduz ``ConfigError`` em
mensagem amigável — falha de ambiente nunca vira traceback para o usuário.
"""

__all__ = ["ConfigError", "InvalidResponseError"]


class ConfigError(Exception):
    """Falha de configuração/ambiente (diretório, permissão, layout)."""


class InvalidResponseError(Exception):
    """Resposta da API com formato inesperado (T08 · §10.1; T10-R2 expande).

    A busca valida a forma (lista de dicts) antes de usar o resultado: uma
    resposta fora do contrato vira erro tipado com mensagem compreensível —
    a UI mostra o caso, nunca um ``AttributeError`` genérico. A taxonomia
    completa (``NetworkError``, ``RateLimitError`` etc.) é o T10-R2.
    """
