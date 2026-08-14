import browser_poller


def test_login_input_matcher_accepts_account_and_password_variants():
    assert browser_poller.login_input_score(
        {"type": "text", "name": "account", "autocomplete": "username"}, "username"
    ) > 0
    assert browser_poller.login_input_score(
        {"type": "password", "autocomplete": "current-password"}, "password"
    ) > 0


def test_login_input_matcher_rejects_non_login_inputs():
    assert browser_poller.login_input_score(
        {"type": "search", "name": "search"}, "username"
    ) == 0
    assert browser_poller.login_input_score(
        {"type": "hidden", "name": "username"}, "username"
    ) == 0


def test_login_input_matcher_allows_unlabelled_visible_text_fallback():
    assert browser_poller.login_input_score({"type": "text"}, "username") > 0
