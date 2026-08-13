import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from alerts import AlertStateMachine, DiscordNotifier, TelegramNotifier, notifier_from_environment


class RecordingNotifier:
    def __init__(self):
        self.events = []

    def send(self, event, message):
        self.events.append((event, message))


@contextmanager
def alert_state_directory():
    root = Path.cwd() / ".codex-tmp"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        yield Path(directory)


def test_alerts_once_on_the_third_consecutive_failure_and_not_before():
    with alert_state_directory() as directory:
        _assert_alerts_once_on_the_third_consecutive_failure(directory)


def _assert_alerts_once_on_the_third_consecutive_failure(directory):
    notifier = RecordingNotifier()
    alerts = AlertStateMachine(directory / "alert-state.json", notifier)

    alerts.record_failure("poll failed")
    alerts.record_failure("poll failed")

    assert notifier.events == []
    assert json.loads((directory / "alert-state.json").read_text()) == {
        "consecutive_failures": 2,
        "failure_alerted": False,
    }

    alerts.record_failure("poll failed")
    alerts.record_failure("poll failed")

    assert len(notifier.events) == 1
    assert notifier.events[0][0] == "failure"


def test_alert_state_survives_restart_and_recovery_is_sent_once():
    with alert_state_directory() as directory:
        _assert_alert_state_survives_restart(directory)


def _assert_alert_state_survives_restart(directory):
    state_path = directory / "alert-state.json"
    first_notifier = RecordingNotifier()
    first_process = AlertStateMachine(state_path, first_notifier)
    for _ in range(3):
        first_process.record_failure("poll failed")

    second_notifier = RecordingNotifier()
    restarted_process = AlertStateMachine(state_path, second_notifier)
    restarted_process.record_failure("poll failed")
    restarted_process.record_success()
    restarted_process.record_success()

    assert [event for event, _ in first_notifier.events] == ["failure"]
    assert [event for event, _ in second_notifier.events] == ["recovery"]
    assert json.loads(state_path.read_text()) == {
        "consecutive_failures": 0,
        "failure_alerted": False,
    }


def test_recovery_is_quiet_when_the_failure_threshold_was_not_reached():
    with alert_state_directory() as directory:
        _assert_recovery_is_quiet_below_threshold(directory)


def _assert_recovery_is_quiet_below_threshold(directory):
    notifier = RecordingNotifier()
    alerts = AlertStateMachine(directory / "alert-state.json", notifier)

    alerts.record_failure("poll failed")
    alerts.record_failure("poll failed")
    alerts.record_success()

    assert notifier.events == []


def test_invalid_persisted_state_starts_a_new_failure_episode():
    with alert_state_directory() as directory:
        state_path = directory / "alert-state.json"
        state_path.write_text('{"consecutive_failures":"not-a-number","failure_alerted":true}')

        alerts = AlertStateMachine(state_path, RecordingNotifier())

        assert alerts._state == {"consecutive_failures": 0, "failure_alerted": False}


def test_core_service_persists_alert_state_on_the_vps_volume():
    service = Path("deploy/bitget-tracker-core.service.example").read_text(encoding="utf-8")

    assert "Environment=ALERT_STATE_PATH=/var/lib/bitget-tracker/alert-state.json" in service


def test_selects_discord_or_telegram_from_environment(monkeypatch):
    monkeypatch.setenv("ALERT_PROVIDER", "discord")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    assert isinstance(notifier_from_environment(), DiscordNotifier)

    monkeypatch.setenv("ALERT_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-id")
    assert isinstance(notifier_from_environment(), TelegramNotifier)
