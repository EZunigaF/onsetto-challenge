"""Pydantic models for the Onsetto API.

Request models carry client-side validation that mirrors the challenge rules
(routing length, Luhn, future expiry, ...). Validating before we hit the network
gives fast, local feedback and saves requests against the rate limit.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, field_validator, model_validator


def _luhn_valid(number: str) -> bool:
    """Return True if ``number`` (digits only) passes the Luhn checksum."""
    digits = [int(d) for d in number]
    checksum = 0
    parity = len(digits) % 2
    for i, digit in enumerate(digits):
        if i % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


# --- Auth ---------------------------------------------------------------------


class TokenResponse(BaseModel):
    mfa_required: bool = True
    mfa_token: str
    message: str | None = None


class MfaVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str | None = None


# --- Banking ------------------------------------------------------------------


class BankingRequest(BaseModel):
    routing_number: str = Field(..., description="9-digit ABA routing number")
    account_number: str = Field(..., description="4-17 digit account number")

    @field_validator("routing_number")
    @classmethod
    def _routing_rules(cls, v: str) -> str:
        if not (v.isdigit() and len(v) == 9):
            raise ValueError("routing_number must be exactly 9 digits")
        return v

    @field_validator("account_number")
    @classmethod
    def _account_rules(cls, v: str) -> str:
        if not (v.isdigit() and 4 <= len(v) <= 17):
            raise ValueError("account_number must be 4-17 digits")
        return v


class BankingResponse(BaseModel):
    routing_masked: str
    account_masked: str
    token: str


# --- Payment ------------------------------------------------------------------


class PaymentRequest(BaseModel):
    cardholder_name: str = Field(..., min_length=1)
    card_number: str = Field(..., description="Luhn-valid card number, digits only")
    exp_month: int = Field(..., ge=1, le=12)
    exp_year: int
    cvc: str

    @field_validator("card_number")
    @classmethod
    def _card_rules(cls, v: str) -> str:
        if not v.isdigit() or not _luhn_valid(v):
            raise ValueError("card_number must be digits and pass the Luhn check")
        return v

    @field_validator("cvc")
    @classmethod
    def _cvc_rules(cls, v: str) -> str:
        if not (v.isdigit() and 3 <= len(v) <= 4):
            raise ValueError("cvc must be 3-4 digits")
        return v

    @model_validator(mode="after")
    def _expiry_in_future(self) -> PaymentRequest:
        today = dt.date.today()
        # An expiry is valid through the last day of its month.
        if (self.exp_year, self.exp_month) < (today.year, today.month):
            raise ValueError("card expiry must be in the future")
        return self


class PaymentResponse(BaseModel):
    card_brand: str
    last4: str
    exp_month: int
    exp_year: int
    token: str
