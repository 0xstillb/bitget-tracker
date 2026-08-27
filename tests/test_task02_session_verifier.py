import asyncio

import pytest

import browser_poller


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"status": 200, "code": "00000", "msg": "success"}, "valid"),
        ({"status": 200, "code": "00004", "msg": "session expired"}, "expired"),
        ({"status": 200, "code": "00004", "msg": "request failed"}, "expired"),
        ({"status": 302, "code": None}, "expired"),
        ({"status": 200, "error": "html_redirect"}, "expired"),
        ({"status": 429, "code": None}, "transient"),
        ({"status": 503, "code": None}, "transient"),
        ({"status": 200, "code": "40001", "msg": "bad request"}, "invalid"),
    ],
)
def test_classifies_authenticated_bitget_responses(response, expected):
    assert browser_poller.classify_session_response(response) == expected


def test_classifies_timeouts_as_transient():
    assert browser_poller.classify_session_response(asyncio.TimeoutError()) == "transient"


def test_refuses_to_persist_cookie_without_current_cycle_verification(monkeypatch):
    class Context:
        async def cookies(self, _url):
            return [{"name": "bt_newsessionid", "value": "replacement", "domain": ".bitget.com"}]

    class CookieFile:
        contents = '{"cookie": "bt_newsessionid=last-good"}'

        def exists(self):
            return True

        def read_text(self):
            return self.contents

        def write_text(self, contents):
            self.contents = contents

    cookie_file = CookieFile()
    monkeypatch.setattr(browser_poller, "COOKIES_FILE", cookie_file)
    monkeypatch.setitem(browser_poller._status, "session_verified_this_cycle", False)

    asyncio.run(browser_poller._persist_refreshed_cookies(Context()))

    assert cookie_file.contents == '{"cookie": "bt_newsessionid=last-good"}'


def test_refuses_to_persist_cookie_after_a_transient_response(monkeypatch):
    class Context:
        async def cookies(self, _url):
            return [{"name": "bt_newsessionid", "value": "replacement", "domain": ".bitget.com"}]

    class CookieFile:
        contents = '{"cookie": "bt_newsessionid=last-good"}'

        def exists(self):
            return True

        def read_text(self):
            return self.contents

        def write_text(self, contents):
            self.contents = contents

    cookie_file = CookieFile()
    monkeypatch.setattr(browser_poller, "COOKIES_FILE", cookie_file)
    monkeypatch.setitem(browser_poller._status, "session_verified_this_cycle", True)
    monkeypatch.setitem(browser_poller._status, "session_state", "transient")

    asyncio.run(browser_poller._persist_refreshed_cookies(Context()))

    assert cookie_file.contents == '{"cookie": "bt_newsessionid=last-good"}'
