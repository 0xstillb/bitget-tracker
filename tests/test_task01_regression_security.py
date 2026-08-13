import asyncio
from pathlib import Path

import httpx

import browser_poller
import main


def test_active_poll_continues_after_one_trader_failure(monkeypatch):
    calls = []

    async def failing_futures(*_args):
        calls.append("futures")
        raise RuntimeError("upstream futures endpoint failed")

    async def successful_cfd(*_args):
        calls.append("cfd")

    monkeypatch.setattr(browser_poller, "_poll_futures_history", failing_futures)
    monkeypatch.setattr(browser_poller, "_poll_cfd_history", successful_cfd)
    monkeypatch.setitem(browser_poller._status, "polls", 0)

    asyncio.run(
        browser_poller._active_poll(
            page=object(),
            push_fn=lambda *_args: None,
            traders={"futures": "1", "cfd": "2"},
            trader_types={"futures": "futures", "cfd": "cfd"},
        )
    )

    assert calls == ["futures", "cfd"]
    assert browser_poller._status["polls"] == 1


def test_poller_status_never_exposes_cookie_contents(monkeypatch):
    monkeypatch.setattr(browser_poller, "_load_cookie_string", lambda: "session=very-secret-value")

    status = browser_poller.get_status()

    assert status["has_cookie"] is True
    assert "cookie_preview" not in status
    assert "very-secret-value" not in repr(status)


def test_credentials_status_never_exposes_api_key_preview(monkeypatch):
    monkeypatch.setattr(main, "_load_credentials", lambda: {"api_key": "key-should-not-leak"})

    status = asyncio.run(main.credentials_status())

    assert status == {"configured": True}


def test_settings_write_requires_write_token(monkeypatch):
    monkeypatch.setattr(main, "_save_settings", lambda _settings: None)
    monkeypatch.setattr(main, "WRITE_TOKEN", "test-write-token")
    monkeypatch.setattr(main, "_settings", {"balance": 0.0, "investment": 0.0, "traders": {}})

    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            denied = await client.post("/api/settings", json={"balance": 12})
            allowed = await client.post(
                "/api/settings",
                json={"balance": 12},
                headers={"X-Write-Token": "test-write-token"},
            )
        return denied, allowed

    denied, allowed = asyncio.run(exercise())

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert main._settings["balance"] == 12


def test_all_write_and_diagnostic_routes_require_write_token():
    expected = {
        ("POST", "/api/push/mt5"),
        ("GET", "/api/mt5/positions/raw"),
        ("GET", "/api/mt5/debug"),
        ("GET", "/api/mt5/sniffs"),
        ("GET", "/api/mt5/raw"),
        ("POST", "/api/settings"),
        ("POST", "/api/traders"),
        ("DELETE", "/api/traders/{name}"),
        ("PATCH", "/api/traders/{name}"),
        ("POST", "/api/traders/{name}/reset"),
        ("GET", "/api/investment/debug"),
        ("POST", "/api/investment/refresh"),
        ("POST", "/api/earn/refresh"),
        ("POST", "/api/futures-leader/refresh"),
        ("POST", "/api/credentials"),
        ("GET", "/api/poller/test"),
        ("POST", "/api/poller/cookie"),
        ("DELETE", "/api/poller/cookie"),
    }
    protected = set()

    for route in main.app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant and any(dep.call is main.require_write_token for dep in dependant.dependencies):
            protected.update((method, route.path) for method in route.methods)

    assert expected <= protected


def test_ignores_cover_runtime_credentials_and_state():
    ignored = Path(".gitignore").read_text(encoding="utf-8")

    for path in ("credentials.json", "history.json", "traders.json"):
        assert path in ignored


def test_write_clients_use_the_write_token_header():
    for path in (
        Path("headless/scraper.js"),
        Path("headless/cookie-bridge.js"),
        Path("scriptable/tampermonkey.js"),
        Path("static/index.html"),
    ):
        assert "X-Write-Token" in path.read_text(encoding="utf-8")
