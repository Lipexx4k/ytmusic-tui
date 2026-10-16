"""Classificação pura de falhas do transporte → erros internos (T10-R2).

Tabela exceção/status → erro interno, sem I/O e sem estado: cada linha é
coberta offline no teste. Os imports são do ``ytmusicapi.exceptions`` (API
pública de erros do ytmusicapi, A3) e de ``requests.exceptions`` — nunca do
pacote ``ytmusicapi`` inteiro, para a fronteira ficar explícita.

Ordem de ``isinstance`` importa (subclasses antes dos pais) e é guardada
por teste de MRO (A3): ``YTMusicGatedError`` ⊂ ``YTMusicServerError``,
``ConnectTimeout``/``SSLError`` ⊂ ``ConnectionError``, ``JSONDecodeError``
⊂ ``ValueError``. O status HTTP existe só na mensagem do ytmusicapi
(``"Server returned HTTP 429: ..."``) — o regex cobre o formato do 1.12.3.

A mensagem final é curta, em pt-BR, com o detalhe técnico que ajuda a
diagnosticar — nunca o payload cru da resposta. ``APIError`` atravessa
intacto: quem levantou já classificou (ex.: a validação de forma do T08) e
o classificador nunca re-embrulha erro interno.
"""

import json
import re

import requests
from ytmusicapi.exceptions import (
    YTMusicError,
    YTMusicGatedError,
    YTMusicServerError,
    YTMusicUserError,
)

from ytmusic_tui.errors import (
    APIError,
    InvalidResponseError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
)

__all__ = ["classify_exception"]

#: Status HTTP embutido na mensagem do ``YTMusicServerError``.
_HTTP_STATUS_RE = re.compile(r"Server returned HTTP (\d{3})\b")


def classify_exception(exc: Exception, *, context: str = "") -> APIError:
    """Traduz a falha crua no erro interno correspondente (T10-R2).

    ``context`` entra no começo da mensagem (ex.: ``busca "coldplay"``) para
    o usuário saber onde falhou; o retorno carrega ``retryable``, que a
    política do T10-R3 usa para decidir a re-tentativa.
    """
    if isinstance(exc, APIError):
        return exc
    prefix = f"{context}: " if context else ""

    # --- falhas de rede (transitórias, exceto TLS/proxy/redirecionamento) --
    if isinstance(exc, requests.exceptions.SSLError):
        # TLS/proxy quebrado não melhora com retry (rede OK, confiança não).
        return NetworkError(f"{prefix}falha de TLS/SSL na conexão: {exc}", retryable=False)
    if isinstance(exc, (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout)):
        kind = "conexão" if isinstance(exc, requests.exceptions.ConnectTimeout) else "leitura"
        return NetworkError(f"{prefix}tempo esgotado ({kind}): {exc}")
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return NetworkError(f"{prefix}falha de rede: {exc}")
    if isinstance(exc, requests.exceptions.TooManyRedirects):
        return ServiceUnavailableError(f"{prefix}excesso de redirecionamentos na API: {exc}")
    if isinstance(exc, requests.exceptions.RequestException):
        return NetworkError(f"{prefix}falha de rede: {exc}")
    if isinstance(exc, OSError):
        # ConnectionError/TimeoutError builtin e sockets crus fora do requests.
        return NetworkError(f"{prefix}falha de rede: {exc}")

    # --- o serviço respondeu algo ------------------------------------------
    if isinstance(exc, YTMusicGatedError):
        return ServiceUnavailableError(
            f"{prefix}o YouTube Music pediu interação (diálogo) e não atendeu: {exc}"
        )
    if isinstance(exc, YTMusicServerError):
        match = _HTTP_STATUS_RE.search(str(exc))
        status = int(match.group(1)) if match else 0
        if status == 429:
            return RateLimitError(
                f"{prefix}limite de requisições do YouTube Music atingido — "
                "tente de novo em instantes"
            )
        if 500 <= status <= 599:
            # 5xx é do serviço, não nosso: transitório de verdade.
            return ServiceUnavailableError(
                f"{prefix}serviço indisponível (HTTP {status}): {exc}", retryable=True
            )
        if status == 404:
            return NotFoundError(f"{prefix}não encontrado no YouTube Music (HTTP 404)")
        return ServiceUnavailableError(f"{prefix}o YouTube Music recusou a requisição: {exc}")
    if isinstance(exc, YTMusicUserError):
        return ServiceUnavailableError(f"{prefix}método indisponível: {exc}")
    if isinstance(exc, YTMusicError):
        return ServiceUnavailableError(f"{prefix}erro do ytmusicapi: {exc}")

    # --- resposta/parsing fora do contrato ----------------------------------
    if isinstance(exc, json.JSONDecodeError):
        return InvalidResponseError(
            f"{prefix}resposta não-JSON da API (esperado JSON, recebido texto inválido)"
        )
    if isinstance(exc, (KeyError, TypeError, AttributeError, ValueError)):
        return InvalidResponseError(
            f"{prefix}resposta fora do contrato do ytmusicapi (possível mudança de formato): "
            f"{exc!r}"
        )

    # --- fallback ------------------------------------------------------------
    return ServiceUnavailableError(f"{prefix}erro inesperado da API: {exc}")
