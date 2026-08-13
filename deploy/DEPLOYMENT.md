# VPS Core and Pi Viewer deployment

Use one deployment method per host: systemd is preferred for both machines;
`compose.vps.example.yml` is an alternative for Core on the VPS only. Do not
run Chromium or the Compose Core service on the Pi.

## Preflight

On both hosts, record the current release, service status, free space, memory,
Tailscale address, and listening ports before changing anything:

```sh
systemctl --no-pager --full status tailscaled
tailscale status
ss -ltnp
df -h
free -h
```

On the Pi, also record the status of Grimmory, moOde, audio, and any existing
web services. Do not stop, disable, restart, or modify Grimmory, moOde, audio
services, their users, their files, their ports, or their systemd units. If
TCP 8080 is occupied, choose a different free Viewer port and update only
`viewer.env`, the ESP32 Viewer URL, and the cloudflared loopback origin.

The units order startup after `network-online.target` and `tailscaled.service`.
They restart with a bounded start rate if the tailnet address is not ready yet.
Verify Tailscale connectivity before treating the deployment as healthy.

## Release and persistent directories

Install source as immutable, root-owned release directories:

```text
/opt/bitget-tracker/releases/<commit>/
/opt/bitget-tracker/current -> /opt/bitget-tracker/releases/<commit>/
```

Create dedicated, non-login users (`bitget` on VPS and `bitget-viewer` on Pi).
Install the matching tmpfiles example under `/etc/tmpfiles.d/`, then run
`systemd-tmpfiles --create`. This creates private mode `0700` state directories:

```text
/var/lib/bitget-tracker       # VPS cookies, snapshot, settings, alert state
/var/lib/bitget-pi-viewer     # Pi last-good Viewer cache only
```

Keep `/etc/bitget-tracker/core.env` and
`/etc/bitget-pi-viewer/viewer.env` root-owned with mode `0600`. Never copy Core
credentials, cookies, browser state, or login-worker files to the Pi.

Copy the relevant unit to `/etc/systemd/system/`, run `systemctl daemon-reload`,
then enable/start only the new Bitget unit. The units write application state
only under their dedicated `/var/lib` directory, log to journald with rate
limits, and enforce CPU, memory, and task limits.

For the Compose alternative, first set `CORE_BIND_HOST` in the external env
file to the VPS Tailscale address. Host networking is intentional so Core can
bind that address; the example has no public `ports:` mapping. Protect the
external state directory and env file with the same ownership/modes as systemd.

## Validation and logs

Use `journalctl -u bitget-tracker-core` on VPS and
`journalctl -u bitget-pi-viewer` on Pi. Confirm restart counts are stable and
resource use remains below the unit limits. Validate:

- Core listens only on loopback or its Tailscale address, never public/LAN.
- Pi can fetch Core over Tailscale with its read-only internal token.
- Viewer serves cached GET routes on the selected LAN port.
- Cloudflare Tunnel exposes only the loopback Viewer origin.
- Grimmory, moOde, audio playback, and their web interfaces remain unchanged.

## Rollback

Keep at least one previous release directory until the new release is proven.
To roll back, stop only the affected Bitget service, repoint `current` to the
previous release using an atomic symlink replacement, run
`systemctl daemon-reload`, and start only that Bitget service. Verify its logs,
private bind address, cached data, and the preflight services again.

Never roll back or delete persistent state automatically. State may have moved
forward independently of code; take a protected backup and review schema
compatibility before restoring any older `/var/lib` content. Compose rollback
uses the previously recorded image digest and the same persistent bind mount.

## Manual validation required

The repository tests can validate unit/config structure only. Perform the full
preflight, Tailscale reachability, systemd/Compose start, restart behavior,
resource pressure, journald rotation, rollback, and Grimmory/moOde coexistence
checks on the actual VPS and Pi before declaring production deployment complete.
