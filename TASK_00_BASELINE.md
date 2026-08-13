# Task 00 — Audit and baseline

Status: audit only. This report records the `origin/integration` baseline at
commit `2d24db8`; no product behavior changed.

## Repository and tests

- The service is a Python 3.12 FastAPI application (`main.py`) using `httpx`,
  `python-dotenv`, and Playwright. `browser_poller.py` runs the Bitget browser
  poller and `bitget_api.py` provides signed private REST calls.
- `headless/` contains a Node/Puppeteer login, cookie refresh/push, and legacy
  scraper path. `scriptable/` contains client-side helper scripts.
- `test_investment_api.py` is a manual, credential-dependent smoke script that
  exits when Bitget credentials are not configured. There was no collected
  automated pytest suite in this baseline. This task adds two audit-artifact
  tests only; it does not exercise or alter product behavior.

## Endpoint inventory

`main.py` declares 35 explicit API routes:

- Portfolio and diagnostic reads: `/api/mt5`, `/api/mt5/traders`,
  `/api/mt5/positions`, `/api/mt5/positions/raw`, `/api/mt5/trades`,
  `/api/mt5/history`, `/api/mt5/debug`, `/api/mt5/sniffs`, `/api/mt5/raw`,
  `/api/journal`, and `/api/prices`.
- Dashboard-facing reads: `/api/widget`, `/api/settings`, `/api/traders`,
  `/api/investment`, `/api/investment/debug`, `/api/earn`,
  `/api/futures-leader`, `/api/elite`, `/api/elite/overview`,
  `/api/credentials/status`, `/api/poller`, and `/api/poller/test`.
- State-changing routes: `/api/push/mt5`, `/api/settings`, `/api/traders`,
  `/api/traders/{name}` (delete and patch), `/api/traders/{name}/reset`,
  `/api/investment/refresh`, `/api/earn/refresh`,
  `/api/futures-leader/refresh`, `/api/credentials`, and the poller cookie
  set/delete routes.
- `GET /api/poller/cookie/export` is disabled unless `COOKIE_SYNC_TOKEN` is
  set, then requires `X-Sync-Token` using constant-time comparison. Other
  write/admin and diagnostic routes have no general authorization dependency.
- CORS permits all origins, methods, and headers while credentials are enabled.

## Secrets and state

- Runtime files default to `settings.json`, `cookies.json`, `traders.json`,
  `history.json`, and `credentials.json`. The tracked `.gitignore` and
  `.dockerignore` exclude the state files they list, `.env`, Python caches,
  local virtual environments, and headless browser/runtime files.
- `credentials.json` contains API key, secret, and passphrase; `cookies.json`
  contains the Bitget cookie and optional local storage. Both are plaintext
  JSON on the configured filesystem.
- `render.yaml` declares neither a persistent disk nor secret values, so the
  default Render filesystem is ephemeral. The recovery workflow supplies
  `TRACKER_URL` and `COOKIE_SYNC_TOKEN` from GitHub secrets.
- No tracked `.env`, cookie file, credential file, PEM/key file, or concrete
  secret value was found in the repository snapshot. Existing untracked
  workspace items were preserved and are outside this task's scope.

## Poller

- The FastAPI lifespan starts the Playwright poller plus investment, Earn, and
  futures-leader refresh loops. The poller launches Chromium, injects the
  configured cookie and local storage, warms Bitget pages, probes positions,
  fetches history/balance data, and updates application caches.
- `_active_poll()` iterates every configured trader and dispatches to CFD or
  futures history polling, then records the poll timestamp/count. It is the
  control-flow surface assigned to Task 01; this audit deliberately makes no
  change to it.
- Refreshed cookies are written only after `auth_ok` is true and an expected
  session cookie is present, preserving the previous cookie for failed or
  incomplete browser jars. Persistence is plaintext and non-atomic.
- Private Bitget endpoints, Cloudflare behavior, Playwright/Chromium runtime
  cost, and cookie/session expiry remain operational risks.

## ESP32

No `esp32/` firmware or device configuration is present in the current
`origin/integration` baseline. Therefore there is no ESP32 endpoint, secret,
build, or deployment path to audit in this task; reconciling it with any
feature-reference implementation is out of scope.

## Deployment

- `Dockerfile` builds from `python:3.12-slim`, installs application
  dependencies plus Playwright Chromium, and starts Uvicorn on port 10000.
- `render.yaml` configures a free Docker web service with placeholder trader
  configuration and a 30-second poll interval.
- `.github/workflows/refresh-cookie.yml` runs every six hours or manually,
  installs Node dependencies and Chrome, then executes the headless verified
  refresh/push process using GitHub secrets.
- `headless/bitget-scraper.service` and setup scripts describe an optional
  Node/VPS deployment path alongside Render and GitHub Actions.

## Risks and follow-up boundaries

Highest-priority findings are unauthenticated state-changing/debug endpoints,
wildcard credentialed CORS, plaintext runtime credentials/cookies, ephemeral
default deployment storage, and reliance on private Bitget/Cloudflare behavior.
Task 01 is scoped to the active-poll regression, secret redaction, unauthenticated
write/admin routes, and ignore hygiene. This task does not redesign architecture,
attempt login/CAPTCHA/OTP automation, alter persistence, introduce MT5 execution,
or merge feature-reference code.

No product behavior changed. References consulted: neither `upstream` nor
`dekkeng` source; only the local task/topology pack was used for instructions.
