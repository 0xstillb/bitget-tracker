# Pi Viewer deployment

Use `INSTALL_PI.md` for the complete first-install and upgrade procedure.

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
The `/` route is a responsive, installable web app for Android Chrome. Use the
browser menu **Install app** or **Add to Home screen**. It is not a native
Android widget; it renders only the Viewer cache through `/api/v1/summary` and
does not retain snapshot data in browser storage.
Full PWA installation and offline app assets require an HTTPS origin. Use the
existing Cloudflare Access/Tunnel deployment for remote Android access, or a
trusted HTTPS reverse proxy on the home network. The plain LAN URL
`http://<PI_LAN_IP>:8080` still serves the dashboard and can be added as a
home-screen shortcut, but it cannot activate the service worker as an
installable PWA.
Use the Pi LAN address for ESP32 devices; keep the Core accessible only through
the Task 04 Tailscale ACL.

For mobile access, follow `CLOUDFLARE_VIEWER.md`. Publish only the Pi Viewer
through Cloudflare Access/Tunnel; never publish Core or the login worker.

Follow `DEPLOYMENT.md` for Pi coexistence checks, resource limits, logging, and
rollback. The Viewer deployment must not alter Grimmory, moOde, or audio services.
