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


def test_pi_viewer_root_is_a_read_only_dashboard_with_external_assets(tmp_path):
    app = ViewerApplication(PiViewer(CoreClient(), ViewerCache(tmp_path / "cache.json")))

    status, headers, html = app.response("GET", "/")
    css_status, css_headers, css = app.response("GET", "/assets/pi-viewer.css")
    js_status, js_headers, script = app.response("GET", "/assets/pi-viewer.js")
    manifest_status, manifest_headers, manifest = app.response("GET", "/manifest.webmanifest")
    worker_status, worker_headers, worker = app.response("GET", "/service-worker.js")

    assert status == 200
    assert "Bitget Pi Viewer" in html
    assert 'href="/assets/pi-viewer.css"' in html
    assert 'src="/assets/pi-viewer.js"' in html
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert "style-src 'self'" in headers["Content-Security-Policy"]
    assert "connect-src 'self'" in headers["Content-Security-Policy"]
    assert css_status == 200 and css_headers["Content-Type"].startswith("text/css") and ".metric" in css
    assert js_status == 200 and js_headers["Content-Type"].startswith("application/javascript")
    assert 'fetch("/api/v1/summary",' in script
    assert 'cache:"no-store"' in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "/internal/" not in script
    assert "POST" not in script
    assert "beforeinstallprompt" in script
    assert manifest_status == 200 and manifest_headers["Content-Type"].startswith("application/manifest+json")
    assert '"display":"standalone"' in manifest
    assert '"src":"/assets/app-icon.svg"' in manifest
    assert worker_status == 200 and worker_headers["Content-Type"].startswith("application/javascript")
    assert '"/api/v1/summary"' not in worker
    assert '"/assets/pi-viewer.js"' in worker


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
