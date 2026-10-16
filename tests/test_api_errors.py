"""Testes do mapeamento exceção → erro interno (T10-R2; A3).

Cada linha da tabela do §11-R2 tem um caso construído com a exceção REAL
(``requests``, ``ytmusicapi.exceptions``, ``json``) e verificado offline —
a classificação é pura. O teste de MRO (A3) guarda a hierarquia das
exceções de terceiros de que a ordem ``isinstance`` do classificador
depende: se uma versão nova reorganizar as classes, o teste aponta antes
de a classificação mudar de comportamento em silêncio.
"""

import json

import pytest
import requests
from ytmusicapi.exceptions import (
    YTMusicError,
    YTMusicGatedError,
    YTMusicServerError,
    YTMusicUserError,
)

from ytmusic_tui.api.classify import classify_exception
from ytmusic_tui.errors import (
    APIError,
    ExtractionError,
    InvalidResponseError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
)


def _server_error(status: int, reason: str = "Erro") -> YTMusicServerError:
    """Constrói o erro do ytmusicapi no formato real (status na mensagem)."""
    return YTMusicServerError(f"Server returned HTTP {status}: {reason}.\n{reason} do servidor")


#: (exceção crua, erro interno esperado, retryable esperado, trecho da mensagem)
CASES: list[tuple[Exception, type[APIError], bool, str]] = [
    (requests.exceptions.ConnectTimeout("connect timed out"), NetworkError, True, "conexão"),
    (requests.exceptions.ReadTimeout("read timed out"), NetworkError, True, "leitura"),
    (requests.exceptions.SSLError("certificate verify failed"), NetworkError, False, "TLS/SSL"),
    (requests.exceptions.ConnectionError("conn refused"), NetworkError, True, "rede"),
    (requests.exceptions.ProxyError("proxy recusou"), NetworkError, True, "rede"),
    (requests.exceptions.Timeout("estourou"), NetworkError, True, "rede"),
    (requests.exceptions.RequestException("genérico"), NetworkError, True, "rede"),
    (
        ConnectionError("Temporary failure in name resolution"),
        NetworkError,
        True,
        "name resolution",
    ),
    (_server_error(429, "Too Many Requests"), RateLimitError, True, "limite"),
    (_server_error(500), ServiceUnavailableError, True, "HTTP 500"),
    (_server_error(503), ServiceUnavailableError, True, "HTTP 503"),
    (_server_error(404, "Not Found"), NotFoundError, False, "HTTP 404"),
    (_server_error(400, "Bad Request"), ServiceUnavailableError, False, "recusou"),
    (_server_error(403, "Forbidden"), ServiceUnavailableError, False, "recusou"),
    (YTMusicServerError("sem status reconhecível"), ServiceUnavailableError, False, "recusou"),
    (YTMusicGatedError("caixa de diálogo"), ServiceUnavailableError, False, "interação"),
    (
        YTMusicUserError("Please provide authentication"),
        ServiceUnavailableError,
        False,
        "indisponível",
    ),
    (YTMusicError("base"), ServiceUnavailableError, False, "ytmusicapi"),
    (
        requests.exceptions.TooManyRedirects("loop"),
        ServiceUnavailableError,
        False,
        "redirecionamentos",
    ),
    (json.JSONDecodeError("Expecting value", "<html>", 0), InvalidResponseError, False, "não-JSON"),
    (KeyError("header"), InvalidResponseError, False, "contrato"),
    (TypeError("x"), InvalidResponseError, False, "contrato"),
    (AttributeError("y"), InvalidResponseError, False, "contrato"),
    (ValueError("z"), InvalidResponseError, False, "contrato"),
    (RuntimeError("boom"), ServiceUnavailableError, False, "inesperado"),
]

IDS = [f"{i:02d}-{type(exc).__name__}-{snippet}" for i, (exc, _, _, snippet) in enumerate(CASES)]


@pytest.mark.parametrize("exc, expected_cls, retryable, snippet", CASES, ids=IDS)
def test_mapping(exc, expected_cls, retryable, snippet):
    """Cada linha da tabela vira (classe, retryable, mensagem) verificados."""
    err = classify_exception(exc)

    assert type(err) is expected_cls
    assert err.retryable is retryable
    assert snippet in str(err)


def test_contexto_entra_no_inicio_da_mensagem():
    """``context`` diz onde falhou, sem mudar a classificação."""
    err = classify_exception(ValueError("v"), context='busca "coldplay"')

    assert isinstance(err, InvalidResponseError)
    assert str(err).startswith('busca "coldplay": ')


def test_erro_interno_atravessa_intacto():
    """APIError já classificado nunca é re-embrulhado (T08 continua verdadeiro)."""
    original = InvalidResponseError("resposta inesperada da API: esperado lista, recebido dict")
    assert classify_exception(original) is original

    net = NetworkError("sem rede")
    assert classify_exception(net) is net


def test_taxonomia_reservada():
    """ExtractionError existe na taxonomia, sem produtor ainda (Q-D)."""
    assert issubclass(ExtractionError, APIError)
    assert ExtractionError.retryable is False


def test_mro_das_excecoes_de_terceiros():
    """A ordem de isinstance do classificador depende desta hierarquia (A3)."""
    # ytmusicapi: o gate é um server error — precisa ser checado antes do pai.
    assert issubclass(YTMusicGatedError, YTMusicServerError)
    assert issubclass(YTMusicServerError, YTMusicError)
    assert issubclass(YTMusicUserError, YTMusicError)

    # requests: subclasses que o classificador separa antes dos pais.
    assert issubclass(requests.exceptions.SSLError, requests.exceptions.ConnectionError)
    assert issubclass(requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError)
    assert issubclass(requests.exceptions.ConnectTimeout, requests.exceptions.Timeout)
    assert issubclass(requests.exceptions.ReadTimeout, requests.exceptions.Timeout)
    assert issubclass(requests.exceptions.Timeout, requests.exceptions.RequestException)
    assert issubclass(requests.exceptions.ConnectionError, requests.exceptions.RequestException)

    # json: o decode é um ValueError — checado antes do genérico.
    assert issubclass(json.JSONDecodeError, ValueError)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
