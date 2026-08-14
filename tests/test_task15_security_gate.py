import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

import core_server
import main


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def test_python_dependencies_have_a_hashed_lock_used_by_the_container():
    lock = _read("requirements.lock")
    dev_lock = _read("requirements-dev.lock")
    dockerfile = _read("Dockerfile")

    assert "--hash=sha256:" in lock
    for direct_dependency in ("fastapi==", "uvicorn==", "python-dotenv==", "playwright==", "httpx=="):
        assert direct_dependency in lock
    assert "COPY requirements.lock ." in dockerfile
    assert "pip install --no-cache-dir --require-hashes -r requirements.lock" in dockerfile
    assert "pytest==" in dev_lock and "--hash=sha256:" in dev_lock


def test_all_github_actions_are_sha_pinned_with_read_only_repository_permissions():
    workflows = list(Path(".github/workflows").glob("*.yml"))
    assert {path.name for path in workflows} >= {"refresh-cookie.yml", "security-gate.yml"}

    for path in workflows:
        workflow = path.read_text(encoding="utf-8")
        assert re.search(r"(?m)^permissions:\s*\n\s+contents:\s*read\s*$", workflow)
        for action in re.findall(r"uses:\s*([^\s#]+)", workflow):
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), f"unpinned action in {path}: {action}"


def test_security_ci_uses_locks_runs_tests_and_runs_the_release_gate():
    workflow = _read(".github/workflows/security-gate.yml")

    assert "pip install --require-hashes -r requirements-dev.lock" in workflow
    assert "python -m pytest tests -q" in workflow
    assert "python tools/security_gate.py" in workflow
    assert "npm ci --ignore-scripts --no-audit --no-fund" in workflow
    assert "npm audit --omit=dev --audit-level=high" in workflow
    assert "pull_request_target" not in workflow
    assert "secrets." not in workflow


def test_node_browser_lock_uses_the_audited_puppeteer_major():
    package = json.loads(_read("headless/package.json"))
    lock = json.loads(_read("headless/package-lock.json"))

    requested = package["dependencies"]["puppeteer"].lstrip("^~>=< ")
    assert int(requested.split(".", 1)[0]) >= 25
    assert package["engines"]["node"] == ">=22.12.0"
    assert lock["packages"]["node_modules/puppeteer"]["version"].split(".", 1)[0] >= "25"
    assert 'node-version: "22"' in _read(".github/workflows/security-gate.yml")
    assert "node-version: 22" in _read(".github/workflows/refresh-cookie.yml")
    assert "setup_22.x" in _read("headless/setup-vps.sh")
    assert "setup_22.x" in _read("headless/setup-gcp.sh")


def test_core_responses_have_no_store_and_csp_security_headers():
    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/poller")

    response = asyncio.run(exercise())

    assert response.headers["cache-control"] == "no-store, max-age=0"
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize(
    "raw",
    [
        "*",
        "http://localhost, *",
        "javascript:alert(1)",
        "https://viewer.example/path",
        "https://user:password@example.com",
    ],
)
def test_cors_configuration_rejects_wildcards_and_non_origins(raw):
    parser = getattr(core_server, "parse_cors_origins")

    with pytest.raises(ValueError):
        parser(raw)


def test_cors_configuration_accepts_only_explicit_http_origins():
    parser = getattr(core_server, "parse_cors_origins")

    assert parser("http://localhost, https://viewer.example") == (
        "http://localhost",
        "https://viewer.example",
    )


def test_dashboard_escapes_api_and_user_values_before_inner_html():
    dashboard = _read("static/index.html")

    for unsafe in (
        "${p.symbol}",
        "${p.side}",
        "${t.symbol}",
        "${t.time}",
        "${it.coin}",
        "${t.pushed_at ||",
        "${name} added",
        "${res.error || 'unknown'}",
        "' + (res.error || 'unknown') + '",
        "resetTraderData('${t.name}')",
        "removeTrader('${t.name}')",
        "saveTraderEdit('${t.name}'",
    ):
        assert unsafe not in dashboard

    for safe in ("${esc(p.symbol)}", "${esc(t.symbol)}", "${esc(it.coin)}", "${esc(res.error || 'unknown')}"):
        assert safe in dashboard
    assert "fonts.googleapis.com" not in dashboard
    assert "fonts.gstatic.com" not in dashboard


def test_cookie_export_is_fail_closed_and_never_returns_cookie_without_sync_token(monkeypatch):
    monkeypatch.setenv("COOKIE_SYNC_TOKEN", "sync-test-token")

    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/poller/cookie/export")

    response = asyncio.run(exercise())

    assert response.status_code == 403
    assert "cookie" not in response.json()


def test_exposure_acl_and_browser_isolation_remain_narrow():
    acl = _read("deploy/tailscale-acl.example.hujson")
    tunnel = _read("deploy/cloudflared-config.example.yml")
    protocol = _read("login_protocol.py")
    worker = _read("headless/login-worker.js").lower()

    assert '"src": ["tag:bitget-viewer"]' in acl
    assert '"dst": ["tag:bitget-core"]' in acl
    assert '"ip": ["tcp:10000"]' in acl
    assert "service: http://127.0.0.1:8080" in tunnel and "10000" not in tunnel
    assert '"password"' not in protocol and '"phone"' not in protocol
    for forbidden in ("placeorder", "place_order", "closeposition", "cancelorder", "modify_sl"):
        assert forbidden not in worker


def test_release_checklist_covers_recovery_rollback_and_manual_host_validation():
    checklist = _read("SECURITY_RELEASE_GATE.md").lower()

    assert "no auto-merge" in checklist
    assert "rollback" in checklist
    assert "recovery" in checklist
    assert "vps" in checklist and "pi" in checklist
    assert "cloudflare access" in checklist
    assert "grimmory" in checklist and "moode" in checklist
    assert "manual validation" in checklist


def test_automated_security_gate_passes_repository_invariants():
    completed = subprocess.run(
        [sys.executable, "tools/security_gate.py"],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "security gate passed" in completed.stdout.lower()
