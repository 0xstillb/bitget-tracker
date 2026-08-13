# Security and release gate

This checklist is required before promoting `integration`. It does not authorize
deployment and it does not change the repository rule: no auto-merge. Review and
merge each task explicitly in `0xstillb/bitget-tracker` only.

## Automated gate

- Run `python -m pytest tests -q` and `python tools/security_gate.py`.
- Install Python with `requirements.lock --require-hashes` and Node with
  `npm ci` from `headless/package-lock.json`.
- Confirm GitHub Actions have read-only repository permissions, SHA-pinned
  actions, no `pull_request_target`, and no secrets in the PR security workflow.
- Re-run diff, tracked-secret, private-key, runtime-state, ACL, Tunnel, CORS,
  CSP/XSS, token-boundary, and browser-isolation checks.

## Manual validation on real infrastructure

- VPS: confirm Core binds only loopback/Tailscale, public scans cannot reach it,
  state/env permissions are private, browser/login worker stays on VPS, and
  journald/resource/restart limits behave as documented.
- Pi: confirm Viewer is GET-only, LAN firewall rules are correct, cached stale
  behavior works, and Grimmory/moOde/audio services remain unchanged.
- Cloudflare Access: verify deny-by-default identity policy, MFA/session policy,
  one Viewer hostname, 404 catch-all, and no Core/worker ingress.
- Exercise session expiry, failed renewal, OTP/CAPTCHA/approval, Core/Tailscale,
  Cloudflare, and restart outages. Confirm last-good data is never zeroed and
  only one failure/recovery alert is delivered per episode.

## Recovery and rollback

Perform the recovery steps in `RECOVERY.md` without bypassing Bitget security.
Test the deployment rollback in `deploy/DEPLOYMENT.md` using the previous
release while preserving `/var/lib` state. Verify Core, Pi cache, alerts,
Cloudflare Access, Grimmory, and moOde after rollback.

Record reviewer, commit SHA, test output, dependency-lock update date, host
validation evidence, rollback result, known risks, and release decision. A local
or CI pass alone is not proof that VPS/Pi/Cloudflare production controls work.
