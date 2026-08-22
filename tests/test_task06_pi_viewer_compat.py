import json
import tempfile
from pathlib import Path

from pi_viewer import PiViewer, ViewerApplication, ViewerCache, _refresh_interval_from_env


class CoreClient:
    def fetch(self):
        return {
            "version": 1,
            "updated_at": "2026-08-13T15:00:00+00:00",
            "data": {
                "summary": {
                    "total_balance": 120.0, "total_investment": 100.0,
                    "daily_pnl": 2.0, "open_positions_pnl": 1.0,
                    "open_positions": 4, "all_time_pnl": 20.0, "pushed_at": "15:00",
                },
                "traders": [{"name": "Alpha", "balance": 120.0, "daily_pnl": 2.0,
                             "all_time_pnl": 20.0, "open_positions_pnl": 1.0,
                             "open_position_count": 4, "has_data": True}],
                "earn": {"total": 3.0, "interest_24h": 0.2},
                "elite": {"on": False, "bal": 0.0},
                "positions": [
                    {"s": "XAUUSD", "d": "L", "sz": 0.1, "e": 2300.0, "u": 1.0, "src": "core"},
                    {"s": "BTCUSDT", "d": "S", "sz": 0.2, "e": 60000.0, "u": -2.0, "src": "core"},
                    {"s": "ETHUSDT", "d": "L", "sz": 1.0, "e": 3000.0, "u": 0.5, "src": "core"},
                    {"s": "SOLUSDT", "d": "L", "sz": 2.0, "e": 150.0, "u": 0.1, "src": "core"},
                ],
                "history": [{"t": "08-13 14:00", "s": "XAUUSD", "d": "L", "p": 2.0}],
            },
        }


def test_pi_viewer_serves_esp32_compatibility_routes_from_its_local_cache():
    with tempfile.TemporaryDirectory(dir=Path(".codex-tmp")) as directory:
        viewer = PiViewer(CoreClient(), ViewerCache(Path(directory) / "viewer-cache.json"), clock=lambda: 1.0)
        app = ViewerApplication(viewer)

        status, _headers, body = app.response("GET", "/api/esp32")
        home = json.loads(body)
        assert status == 200
        assert home["bal"] == 123.0
        assert len(home["positions"]) == 3

        status, _headers, body = app.response("GET", "/api/esp32/positions")
        assert status == 200
        assert len(json.loads(body)["positions"]) == 4

        status, _headers, body = app.response("GET", "/api/esp32/history?n=1")
        assert status == 200
        assert json.loads(body) == {"trades": [{"t": "08-13 14:00", "s": "XAUUSD", "d": "L", "p": 2.0}]}


def test_pi_viewer_documentation_scopes_esp32_to_cached_get_routes():
    documentation = Path("deploy/PI_VIEWER.md").read_text(encoding="utf-8")

    assert "/api/esp32" in documentation
    assert "GET-only" in documentation


def test_pi_viewer_refresh_interval_defaults_to_three_seconds_and_has_a_safe_floor(monkeypatch):
    monkeypatch.delenv("PI_VIEWER_REFRESH_INTERVAL_SEC", raising=False)
    assert _refresh_interval_from_env() == 3.0

    monkeypatch.setenv("PI_VIEWER_REFRESH_INTERVAL_SEC", "0")
    assert _refresh_interval_from_env() == 1.0
