import browser_poller
from alerts import AlertStateMachine
from pi_viewer import PiViewer, ViewerApplication, ViewerCache


def test_pi_auto_login_config_is_disabled_and_bounded_by_default():
    config = browser_poller.read_auto_login_config({})

    assert config == {
        "enabled": False,
        "max_attempts": 2,
        "timeout_sec": 180,
        "headful": True,
        "phone": "",
        "password": "",
    }


def test_pi_auto_login_config_caps_attempts_and_timeout():
    config = browser_poller.read_auto_login_config({
        "AUTO_LOGIN_ENABLED": "true",
        "AUTO_LOGIN_MAX_ATTEMPTS": "99",
        "AUTO_LOGIN_TIMEOUT_SEC": "9999",
        "BITGET_PHONE": "user",
        "BITGET_PASSWORD": "pass",
    })

    assert config == {
        "enabled": True,
        "max_attempts": 3,
        "timeout_sec": 300,
        "headful": True,
        "phone": "user",
        "password": "pass",
    }


def test_pi_auto_login_classifies_human_verification_states():
    assert browser_poller.classify_login_page_snapshot({"text": "Approve this login in your Bitget app"}) == (
        "approval_required", "approval_pending"
    )
    assert browser_poller.classify_login_page_snapshot({"text": "Enter verification code"}) == (
        "otp_required", "otp_pending"
    )
    assert browser_poller.classify_login_page_snapshot({"selectors": ["iframe[src*=captcha]"]}) == (
        "captcha_required", "captcha_pending"
    )


def test_internal_status_is_available_only_as_a_secret_free_core_route():
    source = open("main.py", encoding="utf-8").read()

    assert '@app.get("/internal/v1/status", dependencies=[Depends(require_internal_token)])' in source
    route = source[source.index('async def get_internal_status'):source.index('async def get_internal_status') + 1000]
    assert '"cookie":' not in route
    assert '"has_cookie"' in route


def test_pi_viewer_exposes_safe_auth_state_for_app_approval(tmp_path):
    class Client:
        def fetch(self):
            return {"version": 1, "updated_at": "now", "data": {"summary": {}}}

        def fetch_status(self):
            return {"login_state": "approval_required", "login_code": "approval_pending"}

    app = ViewerApplication(PiViewer(Client(), ViewerCache(tmp_path / "cache.json")))
    status, _headers, body = app.response("GET", "/api/v1/auth")

    assert status == 200
    assert body == '{"login_state": "approval_required", "login_code": "approval_pending"}'


def test_auth_alert_is_specific_deduplicated_and_recovers(tmp_path):
    class Notifier:
        def __init__(self):
            self.events = []

        def send(self, event, message):
            self.events.append((event, message))

    notifier = Notifier()
    alerts = AlertStateMachine(tmp_path / "alert-state.json", notifier)

    alerts.record_auth_failure("Bitget cookie expired; approval is required in the Bitget app")
    alerts.record_auth_failure("Bitget auto-login still waiting for approval")
    alerts.record_auth_success()

    assert notifier.events == [
        ("auth_failure", "Bitget Tracker auth alert: Bitget cookie expired; approval is required in the Bitget app"),
        ("auth_failure", "Bitget Tracker auth alert: Bitget auto-login still waiting for approval"),
        ("auth_recovery", "Bitget Tracker auth recovery: Bitget login is working again."),
    ]


def test_auto_login_alert_reason_is_safe_and_does_not_include_credentials(tmp_path, monkeypatch):
    class Notifier:
        def __init__(self):
            self.events = []

        def send(self, event, message):
            self.events.append((event, message))

    notifier = Notifier()
    alerts = AlertStateMachine(tmp_path / "alert-state.json", notifier)
    monkeypatch.setenv("AUTO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("BITGET_PHONE", "private-user")
    monkeypatch.setenv("BITGET_PASSWORD", "private-password")

    browser_poller._record_auto_login_alert(alerts, "failed", "attempts_exhausted")

    assert notifier.events[0][0] == "auth_failure"
    assert "bounded retry limit" in notifier.events[0][1]
    assert "private-user" not in notifier.events[0][1]
    assert "private-password" not in notifier.events[0][1]


def test_pi_auto_login_docs_configure_discord_without_exposing_it_to_viewer():
    docs = open("deploy/PI_AUTO_LOGIN.md", encoding="utf-8").read()
    viewer_env = open("deploy/pi-viewer.env.example", encoding="utf-8").read()

    assert "ALERT_PROVIDER=discord" in docs
    assert "DISCORD_WEBHOOK_URL=" in docs
    assert "auth_failure" in docs
    assert "auth_recovery" in docs
    assert "DISCORD_WEBHOOK_URL" not in viewer_env
