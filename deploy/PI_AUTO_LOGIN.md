# Pi Core cookie auto-login

This optional mode is for the current home-Pi topology. Core keeps the
last-good Bitget cookie on the Pi, verifies it on every poll cycle, and renews
it before expiry when Bitget accepts the existing session.

If the cookie is expired, Core opens a private headless Chromium login flow,
enters the configured phone/email and password, then waits for the user to
approve the login in the Bitget App. It never bypasses CAPTCHA, OTP, or device
approval. A replacement cookie is written only after a real authenticated
Bitget endpoint returns success.

## Core environment

Add these values to the Pi-only Core env file. Keep the file mode `0600` and
never commit it:

```dotenv
COOKIES_PATH=/data/cookies.json
AUTO_LOGIN_ENABLED=true
AUTO_LOGIN_MAX_ATTEMPTS=2
AUTO_LOGIN_TIMEOUT_SEC=180
BITGET_PHONE=your-login-email-or-phone
BITGET_PASSWORD=your-bitget-password

# Optional one-shot Discord alerts. Keep the webhook only in the Pi Core env.
ALERT_PROVIDER=discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/replace-me
ALERT_STATE_PATH=/data/alert-state.json
```

Seed the first session with a manually verified `BITGET_COOKIE` or an existing
`/data/cookies.json`. The login credentials are only used when that session is
no longer authenticated; they are not sent to the Pi Viewer or ESP32.

## Discord alerts

When Discord is configured, Core sends one persistent `auth_failure` alert
when the cookie is missing/expired and auto-login is disabled, rejected, is
waiting for Bitget App approval, needs OTP/CAPTCHA, or exhausts its bounded
attempts. It sends one `auth_recovery` alert after a verified login succeeds.
The existing generic poll-health alert remains separate and still uses its
three-consecutive-failure threshold. Repeated poll cycles do not spam Discord;
the incident state is stored in `/data/alert-state.json`.

The webhook URL is never returned by `/internal/v1/status`, the Viewer API, or
ESP32 endpoints. Do not paste it into the Viewer env, browser, firmware, or
GitHub issue/PR.

## Run and approve

Restart the Core container after editing the env file. On the next expired
session, open the Pi Viewer:

```text
http://<PI_LAN_IP>:8080
```

The equity card shows the safe auth state. When it says `APP APPROVAL
REQUIRED`, approve the login in the Bitget App. `OTP REQUIRED` and `CAPTCHA
REQUIRED` mean a person must complete that step; the worker stops and does not
try to solve it.

The private Core status route is protected by `INTERNAL_API_TOKEN` and is
available only to the Pi Viewer:

```text
GET /internal/v1/status
```

Do not expose Core port 10000 publicly. Do not add a router port-forward for
Core, and do not put `BITGET_PASSWORD` in the Viewer env or any GitHub secret
unless a separate, reviewed deployment explicitly requires it.
