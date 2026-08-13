import asyncio
import json
import tempfile
from pathlib import Path

import browser_poller
from alerts import AlertStateMachine
from login_protocol import LoginEvent, LoginResult, verify_terminal_result
from pi_viewer import PiViewer, ViewerApplication, ViewerCache
from snapshot_store import SnapshotStore


class RecordingNotifier:
    def __init__(self):
        self.events = []

    def send(self, event, message):
        self.events.append((event, message))


def _temporary_directory():
    return tempfile.TemporaryDirectory(dir=Path(".codex-tmp"))


def _snapshot(balance=125.0):
    return {
        "version": 1,
        "updated_at": "2026-08-14T00:00:00+00:00",
        "data": {
            "summary": {"total_balance": balance},
            "traders": [],
            "credential": "must-never-reach-viewer",
        },
    }


def test_healthy_core_to_pi_to_mobile_flow_is_fresh_and_secret_free():
    class HealthyCore:
        def fetch(self):
            return _snapshot()

    with _temporary_directory() as directory:
        viewer = PiViewer(
            HealthyCore(), ViewerCache(Path(directory) / "viewer-cache.json"),
            clock=lambda: 1.0,
        )
        application = ViewerApplication(viewer)

        status, headers, body = application.response("GET", "/api/v1/summary")
        health = viewer.health()

        assert status == 200
        assert headers["Cache-Control"] == "no-store, max-age=0"
        assert json.loads(body)["data"]["summary"]["total_balance"] == 125.0
        assert health["ok"] is True
        assert health["stale"] is False
        assert "must-never-reach-viewer" not in body


def test_core_or_tailscale_outage_keeps_last_good_marks_stale_and_redacts_errors():
    class TailscaleFailure:
        def fetch(self):
            raise TimeoutError("Tailscale unavailable token=top-secret-token")

    with _temporary_directory() as directory:
        cache = ViewerCache(Path(directory) / "viewer-cache.json")
        assert cache.save(_snapshot(balance=88.0)) is True
        viewer = PiViewer(TailscaleFailure(), cache, clock=lambda: 10.0)
        application = ViewerApplication(viewer)

        status, _headers, body = application.response("GET", "/api/v1/summary")
        health = viewer.health()

        assert status == 200
        assert json.loads(body)["data"]["summary"]["total_balance"] == 88.0
        assert health["stale"] is True
        assert "top-secret-token" not in json.dumps(health)
        assert "token=" not in json.dumps(health).lower()


def test_bitget_session_and_renewal_failures_never_zero_or_replace_last_good(monkeypatch):
    class ReplacementCookies:
        async def cookies(self, _url):
            return [{"name": "bt_newsessionid", "value": "unverified", "domain": ".bitget.com"}]

    with _temporary_directory() as directory:
        root = Path(directory)
        snapshot_store = SnapshotStore(root / "snapshot.json")
        assert snapshot_store.save({"summary": {"total_balance": 70.0}}, session_state="valid") is True

        expired = browser_poller.classify_session_response(
            {"status": 200, "code": "00004", "msg": "session expired"}
        )
        assert expired == "expired"
        assert snapshot_store.save({"summary": {"total_balance": 0}}, session_state=expired) is False
        assert snapshot_store.load()["data"]["summary"]["total_balance"] == 70.0

        cookie_path = root / "cookies.json"
        original_cookie = '{"cookie":"bt_newsessionid=last-good"}'
        cookie_path.write_text(original_cookie, encoding="utf-8")
        monkeypatch.setattr(browser_poller, "COOKIES_FILE", cookie_path)
        renewed = asyncio.run(browser_poller._persist_verified_cookie_jar(
            ReplacementCookies(), {"status": 503, "code": None}
        ))

        assert renewed is False
        assert cookie_path.read_text(encoding="utf-8") == original_cookie


def test_login_failure_and_process_restart_preserve_state_and_alert_once():
    with _temporary_directory() as directory:
        root = Path(directory)
        cookie_path = root / "cookies.json"
        cookie_path.write_text('{"cookie":"bt_newsessionid=last-good"}', encoding="utf-8")

        result = asyncio.run(verify_terminal_result(LoginEvent("success"), lambda: False))
        assert result == LoginResult("failed", "verification_failed")
        assert "last-good" in cookie_path.read_text(encoding="utf-8")

        store = SnapshotStore(root / "snapshot.json")
        assert store.save({"summary": {"total_balance": 44.0}}, session_state="valid") is True
        restarted_store = SnapshotStore(root / "snapshot.json")
        assert restarted_store.load()["data"]["summary"]["total_balance"] == 44.0

        state_path = root / "alert-state.json"
        failure_notifier = RecordingNotifier()
        first_process = AlertStateMachine(state_path, failure_notifier)
        for _ in range(4):
            first_process.record_failure("Bitget unavailable")

        recovery_notifier = RecordingNotifier()
        restarted_process = AlertStateMachine(state_path, recovery_notifier)
        restarted_process.record_failure("still unavailable")
        restarted_process.record_success()
        restarted_process.record_success()

        assert [event for event, _ in failure_notifier.events] == ["failure"]
        assert [event for event, _ in recovery_notifier.events] == ["recovery"]


def test_cloudflare_outage_does_not_break_local_viewer_or_expose_core():
    class CoreUnavailable:
        def fetch(self):
            raise ConnectionError("Core unavailable")

    with _temporary_directory() as directory:
        cache = ViewerCache(Path(directory) / "viewer-cache.json")
        cache.save(_snapshot(balance=33.0))
        local_application = ViewerApplication(PiViewer(CoreUnavailable(), cache, clock=lambda: 5.0))

        status, headers, body = local_application.response("GET", "/api/esp32")
        tunnel_config = Path("deploy/cloudflared-config.example.yml").read_text(encoding="utf-8")

        assert status == 200
        assert json.loads(body)["bal"] == 33.0
        assert headers["Cache-Control"] == "no-store, max-age=0"
        assert "service: http://127.0.0.1:8080" in tunnel_config
        assert "10000" not in tunnel_config
