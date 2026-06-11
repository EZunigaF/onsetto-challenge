# Onsetto Engineering Challenge

[![CI](https://github.com/EZunigaF/onsetto-challenge/actions/workflows/ci.yml/badge.svg)](https://github.com/EZunigaF/onsetto-challenge/actions/workflows/ci.yml)

Two ways to update the same account on the Onsetto sandbox — **banking details** and a
**payment method** — implemented as the challenge asks:

| Part | What it does | Stack |
|------|--------------|-------|
| **Part 1** — [`part1_browser/`](part1_browser/) | Browser automation: sign in → simulated MFA → fill both forms on `/app/account` → verify the "last updated" summary | Playwright |
| **Part 2** — [`part2_api/`](part2_api/) | A small typed API client/SDK doing the same updates over REST | httpx + Pydantic |

> ⚠️ This is a **simulation app**. Only fake test data is used (the shared sandbox
> credentials and known test card numbers).

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`pip install uv`)

## Setup

```bash
git clone https://github.com/EZunigaF/onsetto-challenge.git
cd onsetto-challenge
cp .env.example .env        # then set ONSETTO_PASSWORD (from the challenge email)
uv sync --extra dev --extra browser
uv run playwright install chromium    # Part 1 only
```

### Environment variables (`.env`)

| Variable | Purpose | Default |
|----------|---------|---------|
| `ONSETTO_EMAIL` | Sandbox login | `candidate1@onsetto.test` |
| `ONSETTO_PASSWORD` | Sandbox password (from the challenge email) | — |
| `ONSETTO_MFA_CODE` | MFA code (sandbox accepts `1234`) | `1234` |
| `ONSETTO_API_BASE_URL` | Part 2 REST base URL | the published Supabase function URL |
| `ONSETTO_WEB_BASE_URL` | Part 1 challenge site | `https://challenge.onsetto.dev` |
| `HEADLESS` | Part 1: set `0` to watch the browser | `1` |

## Running

**Part 1 — browser automation**
```bash
uv run python part1_browser/automate.py
# HEADLESS=0 uv run python part1_browser/automate.py   # watch it run
```

**Part 2 — API client**
```bash
uv run python part2_api/main.py
```

Both print the masked confirmation the server returns and exit non-zero on failure.

## Quality checks

```bash
uv run ruff check part1_browser part2_api      # lint
uv run ruff format --check part1_browser part2_api
uv run mypy part2_api/onsetto_client part2_api/main.py part1_browser/automate.py
uv run pytest -q                               # 13 tests, API fully mocked
```

All of the above run in [CI](.github/workflows/ci.yml) on every push.

## Approach & tradeoffs

**One repo, two self-contained parts.** Each part reads the same `.env` and shares no
code, so they can be reviewed and run independently.

**Part 2 is built as a reusable SDK, not a script.** [`onsetto_client`](part2_api/onsetto_client/)
owns the two-step auth flow, injects the bearer token, validates inputs, maps HTTP
statuses to a typed exception hierarchy, and retries on rate limits:

- **Pydantic models** ([`models.py`](part2_api/onsetto_client/models.py)) validate
  *before* hitting the network — routing length, 4–17 digit accounts, **Luhn**, future
  expiry, 3–4 digit CVC. Failing locally is faster and saves requests against the
  30 req/min limit.
- **Typed errors** ([`errors.py`](part2_api/onsetto_client/errors.py)) let callers catch
  `OnsettoError` broadly or narrow to `AuthenticationError` / `MfaError` /
  `ValidationError` / `RateLimitError`.
- **Rate-limit retries** ([`retry.py`](part2_api/onsetto_client/retry.py)) use tenacity
  with exponential backoff + jitter, honouring `Retry-After` when the server sends it.
- **httpx over requests** for a modern, typed client with a clean transport seam — which
  is exactly what the tests mock (via `respx`), so the suite is fast, deterministic, and
  needs no network or real credentials.

**Part 1 leans on the provided stable selectors** (`id` / `data-testid`) rather than CSS
classes or text, so it's resilient to styling changes. The key subtlety: after saving,
the script waits for the summary to *actually change to the new value* (not merely to be
visible), which avoids reading a stale "last updated" panel. It uses a card with a
distinct `last4` so the verification step is meaningful.

**What I deliberately left out:** token refresh (the flow completes well within the
1-hour token lifetime), async (the work is sequential and I/O is tiny), and a full Page
Object Model for Part 1 (overkill for two forms). These are noted as natural next steps
rather than hidden gaps.

## Project layout

```
onsetto-challenge/
├── part1_browser/automate.py          # Playwright end-to-end flow
├── part2_api/
│   ├── onsetto_client/                # reusable typed SDK
│   │   ├── client.py · models.py · errors.py · retry.py
│   ├── main.py                        # CLI entry point
│   └── tests/test_client.py           # mocked with respx
├── .github/workflows/ci.yml           # ruff + mypy + pytest
├── pyproject.toml                     # deps + tool config (uv)
└── .env.example
```
