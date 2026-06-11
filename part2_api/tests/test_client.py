"""Tests for the Onsetto client and models.

The API is mocked with respx so the suite is fast, deterministic, and runs in CI
without network access or real credentials.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from onsetto_client import (
    AuthenticationError,
    MfaError,
    OnsettoClient,
    PaymentRequest,
    RateLimitError,
    ValidationError,
)
from onsetto_client.models import BankingRequest, _luhn_valid
from pydantic import ValidationError as PydanticValidationError

BASE = "https://api.test/v1"


def _client() -> OnsettoClient:
    return OnsettoClient(BASE)


# --- model validation ---------------------------------------------------------


def test_luhn_accepts_known_good() -> None:
    assert _luhn_valid("4242424242424242")
    assert not _luhn_valid("4242424242424241")


@pytest.mark.parametrize("routing", ["12345678", "1234567890", "12345678a"])
def test_banking_rejects_bad_routing(routing: str) -> None:
    with pytest.raises(PydanticValidationError):
        BankingRequest(routing_number=routing, account_number="1234567890")


def test_payment_rejects_past_expiry() -> None:
    with pytest.raises(PydanticValidationError):
        PaymentRequest(
            cardholder_name="X",
            card_number="4242424242424242",
            exp_month=1,
            exp_year=2000,
            cvc="123",
        )


def test_payment_rejects_bad_luhn() -> None:
    with pytest.raises(PydanticValidationError):
        PaymentRequest(
            cardholder_name="X",
            card_number="1234567812345678",
            exp_month=1,
            exp_year=2030,
            cvc="123",
        )


# --- auth flow ----------------------------------------------------------------


@respx.mock
def test_full_flow_happy_path() -> None:
    respx.post(f"{BASE}/auth/token").respond(
        json={"mfa_required": True, "mfa_token": "mfa_abc", "message": "ok"}
    )
    respx.post(f"{BASE}/auth/mfa/verify").respond(
        json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 3600}
    )
    banking_route = respx.put(f"{BASE}/account/banking").respond(
        json={"routing_masked": "•••••0021", "account_masked": "••••••7890", "token": "btok_1"}
    )

    with _client() as client:
        client.authenticate("a@b.com", "pw", "1234")
        assert client.is_authenticated
        result = client.update_banking("021000021", "1234567890")

    assert result.account_masked == "••••••7890"
    # bearer token is forwarded on the banking call
    assert banking_route.calls.last.request.headers["Authorization"] == "Bearer tok123"


@respx.mock
def test_bad_credentials_raise_auth_error() -> None:
    respx.post(f"{BASE}/auth/token").respond(401, json={"message": "invalid credentials"})
    with _client() as client, pytest.raises(AuthenticationError):
        client.authenticate("a@b.com", "wrong", "1234")


@respx.mock
def test_wrong_mfa_raises_mfa_error() -> None:
    respx.post(f"{BASE}/auth/token").respond(json={"mfa_token": "mfa_abc"})
    respx.post(f"{BASE}/auth/mfa/verify").respond(401, json={"message": "bad code"})
    with _client() as client, pytest.raises(MfaError):
        client.authenticate("a@b.com", "pw", "0000")


@respx.mock
def test_validation_error_surfaces() -> None:
    respx.post(f"{BASE}/auth/token").respond(json={"mfa_token": "m"})
    respx.post(f"{BASE}/auth/mfa/verify").respond(json={"access_token": "t"})
    respx.put(f"{BASE}/account/banking").respond(422, json={"message": "bad routing"})
    with _client() as client:
        client.authenticate("a@b.com", "pw", "1234")
        with pytest.raises(ValidationError):
            client.update_banking("021000021", "1234567890")


@respx.mock
def test_rate_limit_retries_then_succeeds() -> None:
    respx.post(f"{BASE}/auth/token").respond(json={"mfa_token": "m"})
    respx.post(f"{BASE}/auth/mfa/verify").respond(json={"access_token": "t"})
    route = respx.put(f"{BASE}/account/banking").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "slow down"}),
            httpx.Response(
                200,
                json={"routing_masked": "•••••0021", "account_masked": "••••••7890", "token": "b"},
            ),
        ]
    )
    with _client() as client:
        client.authenticate("a@b.com", "pw", "1234")
        result = client.update_banking("021000021", "1234567890")
    assert result.token == "b"
    assert route.call_count == 2


@respx.mock
def test_rate_limit_exhausts_and_raises() -> None:
    respx.post(f"{BASE}/auth/token").respond(json={"mfa_token": "m"})
    respx.post(f"{BASE}/auth/mfa/verify").respond(json={"access_token": "t"})
    respx.put(f"{BASE}/account/banking").respond(429, headers={"Retry-After": "0"})
    with _client() as client:
        client.authenticate("a@b.com", "pw", "1234")
        with pytest.raises(RateLimitError):
            client.update_banking("021000021", "1234567890")


def test_calling_protected_endpoint_without_auth_raises() -> None:
    with _client() as client, pytest.raises(AuthenticationError):
        client.update_banking("021000021", "1234567890")
