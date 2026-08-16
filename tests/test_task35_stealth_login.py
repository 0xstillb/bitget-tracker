"""Task 35 — mirror the proven reference auto-login (bitget-alert-main login.js).

The reference runs a visible (headful) Chromium with the puppeteer stealth
plugin, first tries a silent session renewal with the existing cookies, and
treats "URL left /login|/signin" as login success. These tests lock that
behaviour into the Python poller without importing Playwright.
"""

import os

import browser_poller


# ---------------------------------------------------------------- launch mode

def test_login_browser_launch_mirrors_reference_headful_by_default(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(browser_poller.sys, "platform", "linux")

    headless, args = browser_poller._login_browser_launch_config()

    assert headless is False
    assert args == browser_poller.LOGIN_CHROMIUM_ARGS


def test_login_browser_uses_only_the_reference_chromium_args():
    assert browser_poller.LOGIN_CHROMIUM_ARGS == [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ]


def test_login_browser_obeys_bitget_headful_off(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(browser_poller.sys, "platform", "linux")
    config = browser_poller.read_auto_login_config({"BITGET_HEADFUL": "false"})

    headless, _args = browser_poller._login_browser_launch_config(config)

    assert headless is True


def test_login_browser_falls_back_to_headless_when_linux_has_no_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(browser_poller.sys, "platform", "linux")
    config = browser_poller.read_auto_login_config({})

    headless, _args = browser_poller._login_browser_launch_config(config)

    assert headless is True


def test_login_browser_stays_headful_on_windows_without_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(browser_poller.sys, "platform", "win32")
    config = browser_poller.read_auto_login_config({})

    headless, _args = browser_poller._login_browser_launch_config(config)

    assert headless is False


def test_auto_login_config_exposes_bounded_headful_toggle():
    assert browser_poller.read_auto_login_config({})["headful"] is True
    assert browser_poller.read_auto_login_config({"BITGET_HEADFUL": "false"})["headful"] is False


# --------------------------------------------------------------------- stealth

def test_stealth_plugin_is_applied_to_the_login_context(monkeypatch):
    applied = []

    class FakeStealth:
        async def apply_stealth_async(self, context):
            applied.append(context)

    monkeypatch.setattr(browser_poller, "_Stealth", FakeStealth)
    context = object()

    import asyncio

    assert asyncio.run(browser_poller._apply_login_stealth(context)) is True
    assert applied == [context]


def test_login_flow_continues_but_warns_when_stealth_is_missing(monkeypatch):
    monkeypatch.setattr(browser_poller, "_Stealth", None)

    import asyncio

    assert asyncio.run(browser_poller._apply_login_stealth(context=object())) is False


# --------------------------------------------------------- silent session refresh

def test_silent_refresh_is_skipped_when_no_cookie_is_stored(monkeypatch):
    monkeypatch.setattr(browser_poller, "_load_cookie_string", lambda: "")

    import asyncio

    assert asyncio.run(browser_poller._try_silent_session_refresh("pid-1")) is False


def test_silent_refresh_persists_only_after_verified_probe(monkeypatch):
    import asyncio

    calls = []

    class Context:
        async def cookies(self, url):
            return [{"name": "bt_newsessionid", "value": "fresh", "domain": ".bitget.com"}]

    class Page:
        pass

    async def fake_verify(_page, portfolio_id):
        calls.append(("verify", portfolio_id))
        return {"status": 200, "code": "00000"}

    async def fake_persist(_context, verification, local_storage=None):
        calls.append(("persist", verification["code"]))
        return True

    monkeypatch.setattr(browser_poller, "_verify_login_page", fake_verify)
    monkeypatch.setattr(browser_poller, "_persist_verified_cookie_jar", fake_persist)

    result = asyncio.run(browser_poller._refresh_session_from_page(Page(), Context(), "pid-1"))

    assert result is True
    assert calls == [("verify", "pid-1"), ("persist", "00000")]


def test_silent_refresh_stops_when_server_invalidated_the_session(monkeypatch):
    import asyncio

    class Context:
        async def cookies(self, url):
            return [{"name": "locale", "value": "en_US", "domain": ".bitget.com"}]

    class Page:
        pass

    async def fake_persist(*_args, **_kwargs):
        raise AssertionError("must not persist an invalidated session")

    monkeypatch.setattr(browser_poller, "_persist_verified_cookie_jar", fake_persist)

    result = asyncio.run(browser_poller._refresh_session_from_page(Page(), Context(), "pid-1"))

    assert result is False


# ------------------------------------------------------------- URL success gate

def test_login_success_is_decided_by_url_leaving_login_page():
    import asyncio

    class Page:
        url = "https://www.bitget.com/copy-trading/cfd-center/my-portfolio/123"

        async def wait_for_timeout(self, milliseconds):
            assert milliseconds == 3_000

    assert asyncio.run(browser_poller._wait_for_login_url(Page(), timeout_sec=30)) is True


def test_login_success_times_out_while_still_on_login_page():
    import asyncio

    class Page:
        url = "https://www.bitget.com/login"

        async def wait_for_timeout(self, milliseconds):
            pass

    assert asyncio.run(browser_poller._wait_for_login_url(Page(), timeout_sec=0.2)) is False


# ------------------------------------------------------------------- packaging

def test_requirements_pin_playwright_stealth():
    requirements = open("requirements.txt", encoding="utf-8").read()

    assert "playwright-stealth==2.0.3" in requirements


def test_env_example_exposes_headful_toggle():
    example = open(".env.example", encoding="utf-8").read()

    assert "BITGET_HEADFUL=true" in example


def test_docker_image_runs_login_under_xvfb():
    dockerfile = open("Dockerfile", encoding="utf-8").read()
    entrypoint = open("docker-entrypoint.sh", encoding="utf-8").read()

    assert "xvfb" in dockerfile
    assert 'CMD ["/app/docker-entrypoint.sh"]' in dockerfile
    assert 'Xvfb :99 -screen 0 1280x720x24 -nolisten tcp -ac' in entrypoint
    assert 'python run_core.py' in entrypoint
