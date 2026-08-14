import importlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

import core_server
from pi_viewer import CoreSnapshotClient


NODE = shutil.which("node")


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "origin",
    [
        "https://viewer.example:not-a-port",
        "https://viewer.example:70000",
        "https://viewer.example:",
        "https://viewer example",
    ],
)
def test_cors_rejects_malformed_or_out_of_range_ports(origin):
    with pytest.raises(ValueError):
        core_server.parse_cors_origins(origin)


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_login_worker_requires_the_canonical_authenticated_endpoint_before_success():
    script = r"""
      const { hasAuthenticatedSession } = require('./headless/login-worker.js');

      function pageWith(responseText, includeAuthCookie = true) {
        return {
          url: () => 'https://www.bitget.com/account',
          cookies: async () => includeAuthCookie
            ? [{name: 'bt_newsessionid', value: 'candidate'}]
            : [],
          evaluate: async callback => {
            const previousFetch = global.fetch;
            global.fetch = async () => ({text: async () => responseText});
            try { return await callback(); }
            finally { global.fetch = previousFetch; }
          }
        };
      }

      (async () => {
        const result = {
          valid: await hasAuthenticatedSession(pageWith('{"code":"00000","msg":"success"}')),
          expired: await hasAuthenticatedSession(pageWith('{"code":"00004","msg":"Log in expired"}')),
          html: await hasAuthenticatedSession(pageWith('<html>login</html>')),
          cookieOnly: await hasAuthenticatedSession(pageWith('{"code":"00000"}', false)),
        };
        process.stdout.write(JSON.stringify(result));
      })().catch(error => { process.stderr.write(error.stack); process.exit(1); });
    """
    completed = subprocess.run(
        [NODE, "-e", script],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "valid": True,
        "expired": False,
        "html": False,
        "cookieOnly": False,
    }


def test_manual_login_path_also_verifies_the_session_before_saving():
    source = _read("headless/login.js")
    wait_function = source[source.index("async function waitForLoginSuccess"):source.index("async function saveCookies")]

    assert "isSessionAuthenticated(page)" in wait_function


@pytest.mark.parametrize(
    "url",
    [
        "https://public.example/internal/v1/snapshot",
        "http://192.168.1.10:10000/internal/v1/snapshot",
        "http://user:password@100.64.0.10:10000/internal/v1/snapshot",
        "http://100.64.0.10:10000/api/poller",
        "http://100.64.0.10:10000/internal/v1/snapshot?token=leak",
    ],
)
def test_pi_rejects_snapshot_urls_that_could_exfiltrate_the_internal_token(url):
    with pytest.raises(ValueError):
        CoreSnapshotClient(url, "viewer-token")


def test_pi_accepts_only_the_canonical_private_snapshot_endpoints():
    for url in (
        "http://100.64.0.10:10000/internal/v1/snapshot",
        "http://127.0.0.1:10000/internal/v1/snapshot",
    ):
        assert CoreSnapshotClient(url, "viewer-token").url == url


def test_pi_snapshot_client_disables_http_redirects():
    source = _read("pi_viewer.py")

    assert "class _NoRedirectHandler" in source
    assert "build_opener(_NoRedirectHandler)" in source


def test_state_writer_is_atomic_and_private_on_posix(monkeypatch):
    state_io = importlib.import_module("state_io")

    with tempfile.TemporaryDirectory(dir=Path(".codex-tmp")) as directory:
        path = Path(directory) / "credentials.json"
        state_io.atomic_write_json(path, {"secret": "last-good"})
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600

        original = path.read_text(encoding="utf-8")

        def fail_replace(_source, _target):
            raise OSError("simulated interrupted replace")

        monkeypatch.setattr(state_io.os, "replace", fail_replace)
        with pytest.raises(OSError):
            state_io.atomic_write_json(path, {"secret": "partial"})

        assert path.read_text(encoding="utf-8") == original
        assert not list(path.parent.glob("*.tmp"))


def test_all_core_json_state_writes_use_the_atomic_writer():
    source = _read("main.py")

    assert "from state_io import atomic_write_json" in source
    assert ".write_text(json.dumps(" not in source
    for state_file in (
        "TRADERS_FILE",
        "SETTINGS_FILE",
        "HISTORY_FILE",
        "CREDENTIALS_FILE",
        "COOKIES_FILE",
    ):
        assert f"atomic_write_json({state_file}" in source


def test_core_systemd_uses_the_release_venv_and_persistent_browser_cache():
    unit = _read("deploy/bitget-tracker-core.service.example")

    assert "ExecStart=/opt/bitget-tracker/current/.venv/bin/python" in unit
    assert "PLAYWRIGHT_BROWSERS_PATH=/var/lib/bitget-tracker/ms-playwright" in unit
    assert "ExecStart=/usr/bin/python3" not in unit


def test_tailscale_example_uses_least_privilege_grants():
    policy = _read("deploy/tailscale-acl.example.hujson")

    assert '"grants"' in policy
    assert '"src": ["tag:bitget-viewer"]' in policy
    assert '"dst": ["tag:bitget-core"]' in policy
    assert '"ip": ["tcp:10000"]' in policy
    assert '"acls"' not in policy


def test_vps_and_pi_install_guides_are_complete_and_linked():
    readme = _read("README.md")
    vps = _read("deploy/INSTALL_VPS.md")
    pi = _read("deploy/INSTALL_PI.md")

    assert "deploy/INSTALL_VPS.md" in readme
    assert "deploy/INSTALL_PI.md" in readme

    for required in (
        "Ubuntu 24.04",
        "origin/integration",
        "requirements.lock",
        "--require-hashes",
        "/opt/bitget-tracker/current/.venv",
        "/etc/bitget-tracker/core.env",
        "chmod 600",
        "tailscale ip -4",
        "systemctl enable --now bitget-tracker-core",
        "/internal/v1/snapshot",
        "Rollback",
    ):
        assert required in vps

    for required in (
        "Raspberry Pi OS",
        "origin/integration",
        "Grimmory",
        "moOde",
        "/etc/bitget-pi-viewer/viewer.env",
        "chmod 600",
        "systemctl enable --now bitget-pi-viewer",
        "/api/v1/health",
        "/api/esp32",
        "Rollback",
    ):
        assert required in pi

    assert "Chromium" not in pi
    assert "Playwright" not in pi
    assert "nodejs" not in pi.lower()
