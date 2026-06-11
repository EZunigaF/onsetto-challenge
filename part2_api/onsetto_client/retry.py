"""Retry helpers.

The API allows 30 requests/minute/user. When we trip that limit the server
returns 429; we back off and retry a bounded number of times. If the response
carries a ``Retry-After`` header we honour it, otherwise we fall back to
exponential backoff with jitter.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .errors import RateLimitError

logger = logging.getLogger("onsetto")

T = TypeVar("T")

_fallback_wait = wait_exponential_jitter(initial=1, max=20)


def _wait_strategy(retry_state: RetryCallState) -> float:
    """Honour the server's Retry-After if present, else exponential jitter."""
    outcome = retry_state.outcome
    if outcome is not None and outcome.failed:
        exc = outcome.exception()
        if isinstance(exc, RateLimitError) and exc.retry_after is not None:
            return exc.retry_after
    return _fallback_wait(retry_state)


def with_rate_limit_retry(max_attempts: int = 4) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: retry a callable on :class:`RateLimitError`."""
    return retry(
        retry=retry_if_exception_type(RateLimitError),
        wait=_wait_strategy,
        stop=stop_after_attempt(max_attempts),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
