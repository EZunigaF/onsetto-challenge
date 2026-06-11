"""A small, typed, reusable client for the Onsetto REST API.

Usage::

    with OnsettoClient(base_url) as client:
        client.authenticate(email, password, mfa_code)
        banking = client.update_banking("021000021", "1234567890")
        payment = client.update_payment(PaymentRequest(...))

The client owns the two-step auth flow (``/auth/token`` -> ``/auth/mfa/verify``),
injects the bearer token on subsequent calls, maps HTTP statuses to a typed
exception hierarchy, and retries on rate limits.
"""

from __future__ import annotations

import logging
from types import TracebackType

import httpx

from .errors import (
    APIError,
    AuthenticationError,
    MfaError,
    OnsettoError,
    RateLimitError,
    ValidationError,
)
from .models import (
    BankingRequest,
    BankingResponse,
    MfaVerifyResponse,
    PaymentRequest,
    PaymentResponse,
    TokenResponse,
)
from .retry import with_rate_limit_retry

logger = logging.getLogger("onsetto")


class OnsettoClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"Content-Type": "application/json"},
        )
        self._access_token: str | None = None

    # --- lifecycle ------------------------------------------------------------

    def __enter__(self) -> OnsettoClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None

    # --- auth -----------------------------------------------------------------

    def authenticate(self, email: str, password: str, mfa_code: str) -> None:
        """Run the full two-step auth flow and cache the bearer token."""
        token_resp = self._request_token(email, password)
        logger.info("Credentials accepted; MFA required")
        verify_resp = self._verify_mfa(token_resp.mfa_token, mfa_code)
        self._access_token = verify_resp.access_token
        logger.info("Authenticated; bearer token acquired (expires in %ss)", verify_resp.expires_in)

    def _request_token(self, email: str, password: str) -> TokenResponse:
        data = self._send(
            "POST", "/auth/token", json={"email": email, "password": password}, auth=False
        )
        return TokenResponse.model_validate(data)

    def _verify_mfa(self, mfa_token: str, code: str) -> MfaVerifyResponse:
        data = self._send(
            "POST",
            "/auth/mfa/verify",
            json={"mfa_token": mfa_token, "code": code},
            auth=False,
        )
        return MfaVerifyResponse.model_validate(data)

    # --- account updates ------------------------------------------------------

    def update_banking(self, routing_number: str, account_number: str) -> BankingResponse:
        payload = BankingRequest(routing_number=routing_number, account_number=account_number)
        data = self._send("PUT", "/account/banking", json=payload.model_dump())
        return BankingResponse.model_validate(data)

    def update_payment(self, payment: PaymentRequest) -> PaymentResponse:
        data = self._send("PUT", "/account/payment", json=payment.model_dump())
        return PaymentResponse.model_validate(data)

    # --- transport ------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            raise AuthenticationError("Not authenticated; call authenticate() first")
        return {"Authorization": f"Bearer {self._access_token}"}

    @with_rate_limit_retry()
    def _send(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        auth: bool = True,
    ) -> dict[str, object]:
        headers = self._auth_headers() if auth else {}
        try:
            response = self._http.request(method, path, json=json, headers=headers)
        except httpx.RequestError as exc:  # network/DNS/timeout
            raise APIError(f"Request to {path} failed: {exc}") from exc
        return self._handle(response, path)

    @staticmethod
    def _handle(response: httpx.Response, path: str) -> dict[str, object]:
        if response.is_success:
            body: dict[str, object] = response.json()
            return body

        detail = OnsettoClient._extract_detail(response)
        status = response.status_code

        if status == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(
                f"Rate limited on {path}: {detail}",
                retry_after=float(retry_after) if retry_after else None,
            )
        if status in (400, 422):
            raise ValidationError(f"Validation failed on {path}: {detail}", status_code=status)
        if status == 401:
            kind = MfaError if "mfa" in path else AuthenticationError
            raise kind(f"Unauthorized on {path}: {detail}", status_code=status)
        if status >= 500:
            raise APIError(f"Server error on {path}: {detail}", status_code=status)
        raise OnsettoError(f"Unexpected {status} on {path}: {detail}", status_code=status)

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text or "<no body>"
        if isinstance(body, dict):
            return str(body.get("message") or body.get("error") or body)
        return str(body)
