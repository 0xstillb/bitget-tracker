import asyncio
import json
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import browser_poller


@contextmanager
def cookie_directory():
    root = Path.cwd() / ".codex-tmp"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        yield Path(directory)


def test_renewal_is_due_only_for_an_expiring_session_cookie():
    now = time.time()
    assert browser_poller._cookie_renewal_due(
        [{"name": "bt_newsessionid", "expires": now + 60}], now=now, threshold_seconds=120
    ) is True
    assert browser_poller._cookie_renewal_due(
        [{"name": "bt_newsessionid", "expires": now + 600}], now=now, threshold_seconds=120
    ) is False
    assert browser_poller._cookie_renewal_due(
        [{"name": "bt_newsessionid", "expires": -1}], now=now, threshold_seconds=120
    ) is False


def test_verified_replacement_atomically_preserves_metadata_and_http_only_cookie(monkeypatch):
    class Context:
        async def cookies(self, _url):
            return [
                {"name": "bt_newsessionid", "value": "renewed", "domain": ".bitget.com", "httpOnly": True},
                {"name": "other", "value": "kept", "domain": ".bitget.com", "httpOnly": False},
            ]

    with cookie_directory() as directory:
        cookie_path = directory / "cookies.json"
        cookie_path.write_text(json.dumps({"cookie": "bt_newsessionid=last-good", "local_storage": {"x": "y"}}))
        monkeypatch.setattr(browser_poller, "COOKIES_FILE", cookie_path)

        assert asyncio.run(browser_poller._persist_verified_cookie_jar(
            Context(), {"status": 200, "code": "00000"}
        )) is True

        persisted = json.loads(cookie_path.read_text())
        assert persisted["cookie"] == "bt_newsessionid=renewed; other=kept"
        assert persisted["local_storage"] == {"x": "y"}
        assert "self_refreshed_at" in persisted


def test_unverified_replacement_keeps_the_last_good_cookie(monkeypatch):
    class Context:
        async def cookies(self, _url):
            return [{"name": "bt_newsessionid", "value": "replacement", "domain": ".bitget.com"}]

    with cookie_directory() as directory:
        cookie_path = directory / "cookies.json"
        original = '{"cookie":"bt_newsessionid=last-good"}'
        cookie_path.write_text(original)
        monkeypatch.setattr(browser_poller, "COOKIES_FILE", cookie_path)

        assert asyncio.run(browser_poller._persist_verified_cookie_jar(
            Context(), {"status": 200, "code": "40001", "msg": "invalid"}
        )) is False
        assert cookie_path.read_text() == original


def test_proactive_renewal_verifies_the_replacement_before_saving(monkeypatch):
    class Context:
        async def cookies(self, _url):
            return [{"name": "bt_newsessionid", "value": "renewed", "domain": ".bitget.com", "expires": time.time() + 60}]

    class Page:
        def __init__(self):
            self.visits = []
            self.verifications = 0

        async def goto(self, url, **_kwargs):
            self.visits.append(url)

        async def evaluate(self, _script, _portfolio_id):
            self.verifications += 1
            return {"status": 200, "code": "00000"}

    with cookie_directory() as directory:
        cookie_path = directory / "cookies.json"
        cookie_path.write_text('{"cookie":"bt_newsessionid=last-good"}')
        monkeypatch.setattr(browser_poller, "COOKIES_FILE", cookie_path)
        monkeypatch.setattr(browser_poller, "COOKIE_RENEWAL_THRESHOLD_SEC", 120)
        page = Page()

        assert asyncio.run(browser_poller._renew_expiring_cookie(page, Context(), "portfolio-1")) is True
        assert page.visits == [f"{browser_poller.BITGET_BASE}/about"]
        assert page.verifications == 1
        assert "renewed" in json.loads(cookie_path.read_text())["cookie"]
