import browser_poller


def test_full_login_cookie_filter_removes_only_bitget_auth_cookies():
    cookies = browser_poller.full_login_cookies(
        "bt_newsessionid=expired; bt_sessonid=expired2; bt_uid=123; "
        "terminalCode=device-abc; BITGET_LOCAL_COOKIE=remembered; locale=en_US"
    )

    names = {cookie["name"] for cookie in cookies}

    assert names == {"terminalCode", "BITGET_LOCAL_COOKIE", "locale"}


def test_full_login_cookie_filter_preserves_device_cookie_values_and_scope():
    cookies = browser_poller.full_login_cookies(
        "bt_newsessionid=expired; terminalCode=device-abc"
    )

    assert cookies == [
        {
            "name": "terminalCode",
            "value": "device-abc",
            "domain": ".bitget.com",
            "path": "/",
        }
    ]
