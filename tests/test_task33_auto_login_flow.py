import asyncio

import browser_poller


def test_login_submit_step_uses_only_the_proven_next_label():
    assert browser_poller.login_flow_config()["submit_labels"] == ("next",)


def test_login_page_settles_before_the_first_interaction():
    events = []

    class Page:
        url = "https://www.bitget.com/login"

        async def goto(self, url, **kwargs):
            events.append(("goto", url, kwargs))

        async def wait_for_load_state(self, state, **kwargs):
            events.append(("load_state", state, kwargs))

        async def wait_for_timeout(self, milliseconds):
            events.append(("timeout", milliseconds))

    asyncio.run(browser_poller._open_login_page(Page()))

    assert events[0][0] == "goto"
    assert events[1][0:2] == ("load_state", "networkidle")
    assert events[2] == ("timeout", 2_000)


def test_login_field_is_typed_sequentially_to_trigger_page_state():
    calls = []

    class Locator:
        @property
        def first(self):
            return self

        async def wait_for(self, **kwargs):
            calls.append(("wait_for", kwargs))

        async def click(self, **kwargs):
            calls.append(("click", kwargs))

        async def fill(self, value):
            calls.append(("fill", value))

        async def press_sequentially(self, value, **kwargs):
            calls.append(("press_sequentially", value, kwargs))

    class Page:
        def locator(self, _selector):
            return Locator()

        async def wait_for_timeout(self, milliseconds):
            calls.append(("timeout", milliseconds))

    asyncio.run(
        browser_poller._fill_login_field(
            Page(), ('input[name="username"]',), "account@example.com", "username"
        )
    )

    assert ("fill", "") in calls
    assert ("press_sequentially", "account@example.com", {"delay": 30}) in calls
    assert ("fill", "account@example.com") not in calls
    assert ("timeout", 300) in calls


def test_unlabelled_input_is_not_filled_without_a_login_form_signal():
    calls = []

    class Input:
        @property
        def first(self):
            return self

        async def wait_for(self, **_kwargs):
            raise TimeoutError()

        async def is_visible(self):
            return True

        async def evaluate(self, _script):
            return {
                "type": "text",
                "name": "",
                "autocomplete": "",
                "inputmode": "",
                "aria_label": "",
            }

        async def fill(self, value):
            calls.append(("fill", value))

    class Inputs:
        async def count(self):
            return 1

        def nth(self, _index):
            return Input()

    class Page:
        def locator(self, selector):
            return Inputs() if selector == "input" else Input()

    try:
        asyncio.run(
            browser_poller._fill_login_field(
                Page(), ('input[name="username"]',), "account@example.com", "username"
            )
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("unlabelled non-login input should not be filled")

    assert calls == []


def test_submit_button_waits_until_it_is_enabled():
    states = ["disabled", "clicked"]
    waits = []

    class Page:
        async def evaluate(self, _script, _labels):
            return states.pop(0)

        async def wait_for_timeout(self, milliseconds):
            waits.append(milliseconds)

    clicked = asyncio.run(
        browser_poller._click_login_button(Page(), ["next"], wait_ms=1_000)
    )

    assert clicked is True
    assert waits
