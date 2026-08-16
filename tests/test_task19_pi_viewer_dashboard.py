import json
from pathlib import Path

from pi_viewer import PiViewer, ViewerApplication, ViewerCache


class CoreClient:
    def fetch(self):
        return {
            "version": 1,
            "updated_at": "2026-08-14T09:00:00+00:00",
            "data": {
                "summary": {
                    "total_balance": 120.0,
                    "total_investment": 100.0,
                    "daily_pnl": 2.5,
                    "open_positions_pnl": -1.0,
                    "all_time_pnl": 20.0,
                    "open_positions": 2,
                    "pushed_at": "09:00",
                },
                "traders": [{"name": "Alpha", "balance": 120.0, "daily_pnl": 2.5}],
                "positions": [{"s": "XAUUSD", "d": "L", "u": 2.5}],
            },
        }


def test_pi_viewer_root_serves_the_real_dashboard_page(tmp_path):
    app = ViewerApplication(PiViewer(CoreClient(), ViewerCache(tmp_path / "cache.json")))

    status, headers, html = app.response("GET", "/")
    css_status, css_headers, css = app.response("GET", "/assets/pi-viewer.css")
    js_status, js_headers, script = app.response("GET", "/assets/pi-viewer.js")
    manifest_status, manifest_headers, manifest = app.response("GET", "/manifest.webmanifest")
    worker_status, worker_headers, worker = app.response("GET", "/service-worker.js")

    # The viewer page is now the real dashboard, served exactly like Core does.
    assert status == 200
    assert "Bitget CFD Tracker" in html
    assert 'href="/journal.html"' in html
    assert "Content-Security-Policy" not in headers  # dashboard uses inline scripts
    assert css_status == 200 and css_headers["Content-Type"].startswith("text/css") and ".metric" in css
    assert js_status == 200 and js_headers["Content-Type"].startswith("application/javascript")
    assert "script-src 'self'" in css_headers["Content-Security-Policy"]
    assert 'fetch("/api/v1/summary",' in script
    assert "beforeinstallprompt" in script
    assert manifest_status == 200 and manifest_headers["Content-Type"].startswith("application/manifest+json")
    assert '"display":"standalone"' in manifest
    assert worker_status == 200 and worker_headers["Content-Type"].startswith("application/javascript")
    assert '"/assets/pi-viewer.js"' in worker


def test_pi_viewer_serves_the_journal_page(tmp_path):
    app = ViewerApplication(PiViewer(CoreClient(), ViewerCache(tmp_path / "cache.json")))

    status, _headers, html = app.response("GET", "/journal.html")

    assert status == 200
    assert "Trading Journal" in html


def test_pi_viewer_proxies_dashboard_api_routes_to_core(tmp_path):
    import json

    class ProxyingClient(CoreClient):
        def __init__(self):
            self.calls = []

        def proxy(self, method, path, body=b""):
            self.calls.append((method, path, body))
            return 200, '{"ok":true}'

    client = ProxyingClient()
    app = ViewerApplication(PiViewer(client, ViewerCache(tmp_path / "cache.json")))

    status, _headers, body = app.response("GET", "/api/poller")
    assert status == 200 and json.loads(body) == {"ok": True}
    status, _headers, _body = app.response("GET", "/internal/v1/status")
    assert status == 200

    assert client.calls == [
        ("GET", "/api/poller", b""),
        ("GET", "/internal/v1/status", b""),
    ]


def test_pi_viewer_rejects_write_methods_to_keep_the_read_only_concept(tmp_path):
    class SpyingClient(CoreClient):
        def proxy(self, *_args, **_kwargs):
            raise AssertionError("write methods must never reach the proxy")

    app = ViewerApplication(PiViewer(SpyingClient(), ViewerCache(tmp_path / "cache.json")))

    status, headers, body = app.response("POST", "/api/poller/cookie", b'{"cookie":"x"}')

    assert status == 405
    assert headers["Allow"] == "GET"
    assert "read-only" in json.loads(body)["detail"]


def test_pi_viewer_injects_the_readonly_flag_only_into_the_dashboard(tmp_path):
    app = ViewerApplication(PiViewer(CoreClient(), ViewerCache(tmp_path / "cache.json")))

    _status, _headers, dashboard = app.response("GET", "/")
    _status, _headers, journal = app.response("GET", "/journal.html")

    assert "window.BITGET_READONLY=true" in dashboard
    assert "window.BITGET_READONLY=true" not in journal


def test_dashboard_readonly_mode_blocks_writes_in_the_page_itself():
    source = Path("static/index.html").read_text(encoding="utf-8")

    assert "window.BITGET_READONLY === true" in source
    assert "document.body.classList.add('readonly')" in source
    assert "function writeFetch(url, options = {})" in source
    assert "if (BITGET_READONLY)" in source


def test_pi_viewer_keeps_esp32_and_viewer_routes_local_not_proxied(tmp_path):
    class SpyingClient(CoreClient):
        def proxy(self, *_args, **_kwargs):
            raise AssertionError("local viewer routes must not hit the proxy")

    app = ViewerApplication(PiViewer(SpyingClient(), ViewerCache(tmp_path / "cache.json")))

    assert app.response("GET", "/api/esp32")[0] == 200
    assert app.response("GET", "/api/v1/summary")[0] == 200
    assert app.response("POST", "/api/v1/summary")[0] == 405
    assert app.response("GET", "/not-found")[0] == 404


def test_pi_dashboard_assets_never_embed_credentials_or_core_admin_routes():
    source = Path("pi_viewer.py").read_text(encoding="utf-8").lower()

    for forbidden in ("bitget_cookie", "write_token", "cookie_sync_token", "x-write-token", "/api/push"):
        assert forbidden not in source


def test_pi_viewer_docs_explain_android_install_requires_https_and_http_is_a_shortcut():
    documentation = Path("deploy/PI_VIEWER.md").read_text(encoding="utf-8")
    script = ViewerApplication.SECURITY_HEADERS
    source = Path("pi_viewer.py").read_text(encoding="utf-8")

    assert "HTTPS" in documentation
    assert "shortcut" in documentation.lower()
    assert "serviceWorker.register(\"/service-worker.js\").catch" in source
    assert "connect-src 'self'" in script["Content-Security-Policy"]
