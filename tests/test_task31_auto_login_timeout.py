import browser_poller


def test_auto_login_exposes_fallback_selectors_and_safe_interstitial_labels():
    config = browser_poller.login_flow_config()

    assert 'input[name="username"]' in config["username_selectors"]
    assert 'input[autocomplete="username"]' in config["username_selectors"]
    assert 'input[type="password"]' in config["password_selectors"]
    assert "accept all" in config["consent_labels"]
    assert "continue" in config["dialog_labels"]


def test_auto_login_timeout_has_actionable_login_code_without_secret_data():
    state, code = browser_poller.classify_auto_login_error(TimeoutError())

    assert state == "failed"
    assert code == "login_timeout"


def test_playwright_timeout_name_is_classified_without_importing_playwright():
    PlaywrightTimeout = type("TimeoutError", (Exception,), {})

    state, code = browser_poller.classify_auto_login_error(PlaywrightTimeout())

    assert state == "failed"
    assert code == "login_timeout"
