"""CLI entry point for Part 2 — exercises the Onsetto API client end to end.

Reads credentials/config from the environment (see .env.example), authenticates
through the two-step MFA flow, updates banking + payment details, and prints the
masked confirmations the API returns. Errors are reported clearly with a non-zero
exit code so the script is CI/automation friendly.
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from onsetto_client import (
    OnsettoClient,
    OnsettoError,
    PaymentRequest,
)

DEFAULT_API_BASE = "https://zvyhufnwclhcvmgtqxwp.supabase.co/functions/v1/api-v1"

# Sample valid test data (fake, per challenge rules).
SAMPLE_ROUTING = "021000021"
SAMPLE_ACCOUNT = "1234567890"
SAMPLE_CARD = "4242424242424242"  # Luhn-valid Visa test number


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252; ensure masked bullets render correctly."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    load_dotenv()
    _force_utf8_stdout()
    _configure_logging()
    log = logging.getLogger("onsetto.main")

    email = os.getenv("ONSETTO_EMAIL")
    password = os.getenv("ONSETTO_PASSWORD")
    mfa_code = os.getenv("ONSETTO_MFA_CODE", "1234")
    base_url = os.getenv("ONSETTO_API_BASE_URL", DEFAULT_API_BASE)

    if not email or not password:
        log.error("Set ONSETTO_EMAIL and ONSETTO_PASSWORD (copy .env.example to .env).")
        return 2

    try:
        with OnsettoClient(base_url) as client:
            client.authenticate(email, password, mfa_code)

            banking = client.update_banking(SAMPLE_ROUTING, SAMPLE_ACCOUNT)
            print("\nBanking updated:")
            print(f"  routing : {banking.routing_masked}")
            print(f"  account : {banking.account_masked}")
            print(f"  token   : {banking.token}")

            payment = client.update_payment(
                PaymentRequest(
                    cardholder_name="Test User",
                    card_number=SAMPLE_CARD,
                    exp_month=12,
                    exp_year=2030,
                    cvc="123",
                )
            )
            print("\nPayment updated:")
            print(f"  brand   : {payment.card_brand}")
            print(f"  last4   : •••• {payment.last4}")
            print(f"  expiry  : {payment.exp_month:02d}/{payment.exp_year}")
            print(f"  token   : {payment.token}")
    except OnsettoError as exc:
        log.error("Update failed (%s): %s", type(exc).__name__, exc)
        return 1

    print("\nDone — both updates confirmed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
