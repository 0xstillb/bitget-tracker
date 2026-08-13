# Private Core deployment

Run the Core API only on the VPS. Set `CORE_BIND_HOST` to its Tailscale
`100.64.0.0/10` address (or `127.0.0.1` for local testing), set distinct
`WRITE_TOKEN` and `INTERNAL_API_TOKEN` values, then install the systemd example.

The Pi Viewer calls only `GET /internal/v1/snapshot` over Tailscale with
`X-Internal-Token`. It must not receive cookies, Bitget credentials, or raw
Bitget API responses. Apply the ACL example in the Tailscale admin console and
replace the sample node tags before deployment.

`run_core.py` rejects wildcard, LAN, and public bind addresses. Do not publish
the Core through a reverse proxy, Cloudflare Tunnel, or public DNS.

The systemd unit keeps runtime state in `/var/lib/bitget-tracker`, the only
writable path granted by its service sandbox. Create that directory, make it
owned by the `bitget` user, and store `/etc/bitget-tracker/core.env` with mode
`0600` before enabling the service.
