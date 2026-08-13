# Pi Viewer deployment

The Pi runs only `pi_viewer.py`: a GET-only LAN service that fetches the Core
snapshot through Tailscale, keeps an atomic local cache, and serves cached data
when the Core is unavailable. It does not run Chromium, Playwright, or Bitget
login flows.

Copy `pi-viewer.env.example` to `/etc/bitget-pi-viewer/viewer.env`, replace the
Tailscale address and token, set mode `0600`, then install the systemd unit.
Create `/var/lib/bitget-pi-viewer` owned by `bitget-viewer` first.

The native viewer routes are GET-only: `/`, `/api/v1/summary`, and
`/api/v1/health`. For CYD compatibility, the same cache also serves GET-only
`/api/esp32`, `/api/esp32/positions`, and `/api/esp32/history`.
Use the Pi LAN address for ESP32 devices; keep the Core accessible only through
the Task 04 Tailscale ACL.

For mobile access, follow `CLOUDFLARE_VIEWER.md`. Publish only the Pi Viewer
through Cloudflare Access/Tunnel; never publish Core or the login worker.

Follow `DEPLOYMENT.md` for Pi coexistence checks, resource limits, logging, and
rollback. The Viewer deployment must not alter Grimmory, moOde, or audio services.
