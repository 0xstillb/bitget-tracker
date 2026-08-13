import tempfile
from pathlib import Path

from pi_viewer import PiViewer, ViewerApplication, ViewerCache


class CoreClient:
    def fetch(self):
        return {
            "version": 1,
            "updated_at": "2026-08-14T00:00:00+00:00",
            "data": {"summary": {"total_balance": 1.0}, "traders": []},
        }


def _application():
    directory = tempfile.TemporaryDirectory(dir=Path(".codex-tmp"))
    viewer = PiViewer(
        CoreClient(),
        ViewerCache(Path(directory.name) / "viewer-cache.json"),
        clock=lambda: 1.0,
    )
    return directory, ViewerApplication(viewer)


def test_every_viewer_response_has_no_store_and_browser_security_headers():
    directory, application = _application()
    try:
        for method, route in (
            ("GET", "/"),
            ("GET", "/api/v1/summary"),
            ("GET", "/missing"),
            ("POST", "/api/v1/summary"),
        ):
            _status, headers, _body = application.response(method, route)
            assert headers["Cache-Control"] == "no-store, max-age=0"
            assert headers["Content-Security-Policy"] == (
                "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
                "form-action 'none'; object-src 'none'"
            )
            assert headers["X-Content-Type-Options"] == "nosniff"
            assert headers["Referrer-Policy"] == "no-referrer"
            assert headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    finally:
        directory.cleanup()


def test_cloudflared_example_exposes_only_the_loopback_pi_viewer():
    config = Path("deploy/cloudflared-config.example.yml").read_text(encoding="utf-8")
    lowered = config.lower()

    assert "hostname: viewer.example.com" in config
    assert "service: http://127.0.0.1:8080" in config
    assert config.rstrip().endswith("service: http_status:404")
    assert "10000" not in config
    assert "core" not in lowered
    assert "worker" not in lowered
    assert "0.0.0.0" not in config


def test_cloudflare_runbook_requires_access_and_restricts_the_pi_origin():
    runbook = Path("deploy/CLOUDFLARE_VIEWER.md").read_text(encoding="utf-8")
    lowered = runbook.lower()

    assert "cloudflare access" in lowered
    assert "deny by default" in lowered
    assert "127.0.0.1:8080" in runbook
    assert "ufw" in lowered
    assert "lan" in lowered
    assert "core" in lowered and "never" in lowered
    assert "worker" in lowered and "never" in lowered
    assert "no inbound port-forward" in lowered
    assert "manual validation" in lowered


def test_pi_environment_example_keeps_tunnel_origin_local_and_credentials_out():
    environment = Path("deploy/pi-viewer.env.example").read_text(encoding="utf-8")

    assert "PI_VIEWER_BIND_HOST=0.0.0.0" in environment
    assert "CLOUDFLARE_TUNNEL_TOKEN" not in environment
    assert "TUNNEL_CREDENTIALS" not in environment
