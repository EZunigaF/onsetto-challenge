"""Part 1 — Browser automation with Playwright.

Drives the Onsetto challenge site end to end:

    sign in  ->  simulated MFA  ->  update banking  ->  update payment  ->  verify

Selectors are the stable ``id`` / ``data-testid`` hooks the challenge provides
(``#bank-routing``, ``#card-number``, ``#card-save``, ...). After each save we read
the "last updated" summary and assert it reflects the data we submitted.

Config comes from the environment (see ../.env.example):
    ONSETTO_EMAIL, ONSETTO_PASSWORD, ONSETTO_MFA_CODE, ONSETTO_WEB_BASE_URL
    HEADLESS=0 to watch the run in a real window.
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(encoding="utf-8")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("onsetto.browser")

DEFAULT_WEB_BASE = "https://challenge.onsetto.dev"

# Fake test data (challenge rules: simulation app only).
BANK_ROUTING = "021000021"
BANK_ACCOUNT = "9876543210"  # last4 = 3210, used to verify the update
CARD_HOLDER = "Esteban Zuniga"
CARD_NUMBER = "4111111111111111"  # Luhn-valid Visa test number, last4 = 1111
CARD_EXP_MONTH = "11"
CARD_EXP_YEAR = "2031"
CARD_CVC = "123"


def sign_in(page: Page, base_url: str, email: str, password: str) -> None:
    page.goto(f"{base_url}/login", wait_until="networkidle")
    page.fill("#email", email)
    page.fill("#password", password)
    page.get_by_role("button", name="Sign in").click()
    log.info("Submitted credentials")


def complete_mfa(page: Page, code: str) -> None:
    # The OTP widget exposes a single hidden input (data-input-otp). Typing the
    # digits drives the React state and enables the Verify button.
    otp = page.locator("input[data-input-otp]")
    otp.wait_for(state="visible", timeout=15_000)
    otp.click()
    otp.press_sequentially(code, delay=80)
    verify = page.get_by_role("button", name="Verify")
    verify.click()
    log.info("Submitted MFA code")


def update_banking(page: Page, routing: str, account: str) -> str:
    page.fill("#bank-routing", routing)
    page.fill("#bank-account", account)
    page.click("#bank-save")
    # Wait until the summary actually reflects the new account (not the stale value).
    summary = page.locator('[data-testid="bank-saved-info"]').filter(has_text=account[-4:])
    summary.wait_for(state="visible", timeout=10_000)
    text = str(page.get_by_test_id("bank-saved-info").inner_text())
    log.info("Banking summary: %s", text.replace("\n", " | "))
    return text


def update_payment(page: Page) -> str:
    page.fill("#card-holder", CARD_HOLDER)
    page.fill("#card-number", CARD_NUMBER)
    page.fill("#card-exp-month", CARD_EXP_MONTH)
    page.fill("#card-exp-year", CARD_EXP_YEAR)
    page.fill("#card-cvc", CARD_CVC)
    page.click("#card-save")
    summary = page.locator('[data-testid="payment-saved-info"]').filter(has_text=CARD_NUMBER[-4:])
    summary.wait_for(state="visible", timeout=10_000)
    text = str(page.get_by_test_id("payment-saved-info").inner_text())
    log.info("Payment summary: %s", text.replace("\n", " | "))
    return text


def run() -> int:
    load_dotenv()
    email = os.getenv("ONSETTO_EMAIL")
    password = os.getenv("ONSETTO_PASSWORD")
    mfa_code = os.getenv("ONSETTO_MFA_CODE", "1234")
    base_url = os.getenv("ONSETTO_WEB_BASE_URL", DEFAULT_WEB_BASE).rstrip("/")
    headless = os.getenv("HEADLESS", "1") != "0"

    if not email or not password:
        log.error("Set ONSETTO_EMAIL and ONSETTO_PASSWORD (copy .env.example to .env).")
        return 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            sign_in(page, base_url, email, password)
            complete_mfa(page, mfa_code)

            page.goto(f"{base_url}/app/account", wait_until="networkidle")
            log.info("Reached account page")

            bank_text = update_banking(page, BANK_ROUTING, BANK_ACCOUNT)
            payment_text = update_payment(page)

            ok = _verify(bank_text, payment_text)
        except PlaywrightTimeoutError as exc:
            page.screenshot(path="part1_failure.png")
            log.error("Timed out waiting for an element: %s (screenshot: part1_failure.png)", exc)
            return 1
        finally:
            browser.close()

    if not ok:
        log.error("Verification failed — saved summary did not match submitted data")
        return 1
    print("\nPart 1 complete — banking and payment updates verified in the summary.")
    return 0


def _verify(bank_text: str, payment_text: str) -> bool:
    checks = {
        "routing last4": BANK_ROUTING[-4:] in bank_text,
        "account last4": BANK_ACCOUNT[-4:] in bank_text,
        "card last4": CARD_NUMBER[-4:] in payment_text,
        "expiry": f"{int(CARD_EXP_MONTH)}/{CARD_EXP_YEAR}" in payment_text,
    }
    for name, passed in checks.items():
        log.info("verify %-14s %s", name, "OK" if passed else "MISSING")
    return all(checks.values())


if __name__ == "__main__":
    sys.exit(run())
