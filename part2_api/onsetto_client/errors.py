"""Typed exception hierarchy for the Onsetto client.

Callers can catch :class:`OnsettoError` broadly, or narrow to a specific failure
(bad credentials, wrong MFA, validation, rate limit) to drive behaviour.
"""

from __future__ import annotations


class OnsettoError(Exception):
    """Base class for all client errors."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthenticationError(OnsettoError):
    """Bad credentials or an invalid/expired MFA token (HTTP 401)."""


class MfaError(OnsettoError):
    """The submitted MFA code was rejected."""


class ValidationError(OnsettoError):
    """The API rejected the payload (HTTP 400/422)."""


class RateLimitError(OnsettoError):
    """Rate limit exceeded (HTTP 429). Carries retry-after when provided."""

    def __init__(
        self, message: str, *, status_code: int | None = 429, retry_after: float | None = None
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after


class APIError(OnsettoError):
    """Unexpected server-side error (HTTP 5xx) or an unhandled status."""
