# Task 00 — Audit and baseline

Status: complete for audit scope only. This document records the repository as
found on `task/00-baseline`; it does not introduce a runtime behavior change.

## Repository and tests

- The repository is a Python 3.12 FastAPI service (`main.py`) with `httpx`,
  `python-dotenv`, and Playwright dependencies. The root Docker image installs
  Chromium for the in-process browser poller.
- `browser_poller.py` is the cookie-authenticated Bitget browser poller. It
  runs in the FastAPI lifespan unless `DISABLE_POLLER` is set.
- `bitget_api.py` is the signed REST client used for investment and Earn data.
- `headless/` contains a separate Node/Puppeteer login, cookie refresh/push,
  and legacy scraper path. `scriptable/` contains widget/Tampermonkey clients.
- The ESP32 sketch is under `esp32/bitget_dashboard/` and targets the CYD
  ESP32-2432S028R with LVGL 8.3.x.
- No pre-existing automated tests were found in the tracked repository. This
  task adds two tests for this baseline artifact only; no product code is
  exercised or changed by those tests.

## Endpoint inventory

`main.py` currently declares 35 explicit API routes:

- Ingest and portfolio reads: `POST /api/push/mt5`, `GET /api/mt5`,
  `/api/mt5/traders`, `/api/mt5/positions`, `/api/mt5/positions/raw`,
  `/api/mt5/trades`, `/api/mt5/history`, `/api/mt5/debug`,
  `/api/mt5/sniffs`, `/api/mt5/raw`.
- Public market/widget/device reads: `GET /api/prices`, `/api/widget`,
  `/api/esp32`, `/api/esp32/positions`, `/api/esp32/history`,
  `/api/esp32/trader`.
- Settings and trader management: `GET|POST /api/settings`,
  `GET|POST /api/traders`, `DELETE /api/traders/{name}`, and
  `POST /api/traders/{name}/reset`.
- Investment, Earn, and elite: `GET /api/investment`,
  `/api/investment/debug`, `/api/earn`, `/api/elite`; `POST
  /api/investment/refresh` and `/api/earn/refresh`.
- Credentials and poller: `POST /api/credentials`, `GET
  /api/credentials/status`, `GET /api/poller`, `/api/poller/test`,
  `POST /api/poller/cookie`, `DELETE /api/poller/cookie`, and `GET
  /api/poller/cookie/export`.

The audit found no general authentication/authorization dependency on the
state-mutating routes or on the portfolio/debug reads. Cookie export is the
exception: it returns 404 when `COOKIE_SYNC_TOKEN` is unset and otherwise
requires the matching `X-Sync-Token` header using constant-time comparison.
CORS is configured with wildcard origins, credentials, methods, and headers.

## Secrets and state

- Runtime JSON state defaults to `settings.json`, `cookies.json`,
  `traders.json`, `history.json`, and `credentials.json`; each has an env-var
  path override. These files are ignored by `.gitignore` and are not tracked
  in the repository snapshot.
- `.env`, headless `.env`, headless browser data, and ESP32 `secrets.h` are
  ignored. Only `.env.example`, `headless/.env.example`, and
  `esp32/bitget_dashboard/secrets.example.h` are tracked templates.
- Credentials and cookies are persisted as plaintext JSON when the relevant
  endpoints or poller refresh path write them. The deployment configuration
  does not declare a persistent disk, so Render's default filesystem is
  ephemeral and can lose runtime state on redeploy/restart.
- The tracked GitHub Action receives `TRACKER_URL` and `COOKIE_SYNC_TOKEN`
  from repository secrets. The headless example also documents phone/password
  variables for human-assisted full login; no values are committed.
- Pre-existing untracked files in the worktree were preserved and are outside
  this task's scope; they were not staged.

## Poller

- Default poll interval is 30 seconds. The poller reads `BITGET_COOKIE` or
  `cookies.json`, reloads trader configuration each cycle, launches headless
  Chromium, warms Bitget `/about`, probes positions, polls CFD/futures data,
  fetches balances, and pushes normalized data into the in-memory application
  cache.
- It tracks `auth_ok`, last scrape/error, browser health, push count, cookie
  refresh time, and expiry in an in-memory status object exposed by
  `/api/poller`.
- Silent cookie refresh is throttled to six hours and only runs when the
  in-memory auth status is healthy. It persists a newly observed
  `bt_newsessionid`; a failed poll leaves the existing cookie file in place.
- Operational risks recorded for future tasks: the poller depends on Bitget
  private/internal endpoints and Cloudflare behavior; Playwright/Chromium is
  a heavy deployment dependency; the cookie write path is not atomic; and the
  cookie-setting endpoint is not protected by the sync token.

## ESP32

- The device performs GET requests only to the configured backend URL, chiefly
  `/api/esp32`, `/api/esp32/positions`, `/api/esp32/history`,
  `/api/esp32/trader`, `/api/elite`, and `/api/earn`.
- Wi-Fi credentials and backend URL are intended to live in ignored
  `secrets.h`. The sketch supports HTTPS when the configured URL starts with
  `https`; it also permits plain HTTP, which is a deployment/operator risk.
- The device has no API credential or device-auth handshake in the baseline.
  It therefore relies on network placement and the backend's current public
  GET behavior.

## Deployment

- `Dockerfile` builds `python:3.12-slim`, installs Python dependencies and
  Playwright Chromium, copies the repository, and serves `main:app` on port
  10000.
- `render.yaml` declares one free Render Docker web service with `TRADERS`
  and `POLL_INTERVAL_SEC`; it does not declare a persistent disk or secret
  values.
- `.github/workflows/refresh-cookie.yml` runs twice daily or manually,
  installs exact Node dependencies, installs Puppeteer Chrome, and runs the
  headless refresh/push script with GitHub secrets.
- `headless/bitget-scraper.service` and the setup scripts describe an
  alternative VPS/Node deployment. The intended topology is therefore split
  across the Render service, optional headless/VPS tooling, GitHub Actions,
  and the ESP32 client.

## Risks and follow-up boundaries

The highest-risk baseline findings are unauthenticated write/debug surfaces,
wildcard CORS with credentials enabled, plaintext cookie/API credential files,
ephemeral default deployment storage, dependence on private Bitget endpoints,
and optional plaintext HTTP from the ESP32. These are findings only; fixing
them belongs to later scoped tasks. No login, CAPTCHA/OTP, cookie verification
protocol, persistence redesign, API authorization, ESP32 UI change, or
deployment change was implemented here.

No product behavior changed. References consulted for repository topology and
task instructions were the local topology pack only; no upstream or dekkeng
source branch was fetched or modified.
