"""Retry com backoff para falhas transitórias (T10-R3).

A política re-tenta SÓ o que o classificador marcou como ``retryable``
(``NetworkError``, ``RateLimitError``, HTTP 5xx): falha de formato, 404 e
403 não melhoram com insistência. O ``sleep`` é injetável — os testes
rodam com relógio falso, sem espera real.

Semântica do abort (A1): a PRIMEIRA tentativa sempre acontece; o abort é
observado apenas antes/depois de uma NOVA tentativa (antes da pausa e de
novo depois dela, porque a pausa pode durar até ``max_delay``). Quando o
usuário abandona a operação, o último erro classificado sobe na hora,
sem novas tentativas.

Sem jitter de propósito: o teste fica determinístico e o app é
single-user (não há thundering herd a evitar).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from ytmusic_tui.api.classify import classify_exception
from ytmusic_tui.errors import APIError

__all__ = ["RetryPolicy", "call_with_retry"]

logger = logging.getLogger("ytmusic_tui.api")

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Teto de tentativas + backoff progressivo (base × 2, teto ``max_delay``)."""

    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 4.0

    def delay_for(self, attempt: int) -> float:
        """Espera antes da tentativa ``attempt + 1`` (``attempt`` 1-based)."""
        return min(self.base_delay * (2.0 ** (attempt - 1)), self.max_delay)


def call_with_retry(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    context: str = "",
    sleep: Callable[[float], None] = time.sleep,
    should_abort: Callable[[], bool] | None = None,
) -> T:
    """Executa ``operation`` com retry/classificação (T10-R3).

    Erro não-transitório (ou já classificado) sai na hora; transitório é
    re-tentado até o teto, com backoff. Na desistência (teto ou abort), o
    último erro interno classificado é levantado — encadeado na exceção
    crua (``from exc``) para o log preservar a causa.
    """
    if policy.attempts < 1:
        raise ValueError("policy.attempts deve ser >= 1")

    last_error: APIError | None = None
    for attempt in range(1, policy.attempts + 1):
        try:
            return operation()
        except Exception as exc:
            error = classify_exception(exc, context=context)
            if not error.retryable or attempt >= policy.attempts:
                raise error from exc
            last_error = error
            if should_abort is not None and should_abort():
                # Usuário abandonou: sem novas tentativas (A1).
                raise error from exc
            delay = policy.delay_for(attempt)
            logger.info(
                "tentativa %d/%d falhou (%s); nova tentativa em %.1fs",
                attempt,
                policy.attempts,
                error,
                delay,
            )
            sleep(delay)
            if should_abort is not None and should_abort():
                # A pausa pode durar até ``max_delay``: rechecar custa nada.
                raise error from exc

    # Inalcançável: o loop só sai por return/raise; guarda para o mypy.
    if last_error is None:  # pragma: no cover
        raise RuntimeError("retry esgotado sem erro classificado")
    raise last_error  # pragma: no cover
