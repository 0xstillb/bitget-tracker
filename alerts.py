"""Persistent, one-shot health alerts for the Core poller."""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol

import httpx


logger = logging.getLogger(__name__)
FAILURE_THRESHOLD = 3


class Notifier(Protocol):
    """Minimal notification transport used by the alert state machine."""

    def send(self, event: str, message: str) -> None:
        """Deliver one alert event."""


class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, event: str, message: str) -> None:
        response = httpx.post(self.webhook_url, json={"content": message}, timeout=10.0)
        response.raise_for_status()


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, event: str, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        response = httpx.post(url, json={"chat_id": self.chat_id, "text": message}, timeout=10.0)
        response.raise_for_status()


def notifier_from_environment() -> Notifier | None:
    """Build the explicitly configured notification transport, if any."""
    provider = os.environ.get("ALERT_PROVIDER", "").strip().lower()
    if not provider:
        return None
    if provider == "discord":
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
        if webhook_url:
            return DiscordNotifier(webhook_url)
        logger.warning("Alerts disabled: DISCORD_WEBHOOK_URL is not configured")
        return None
    if provider == "telegram":
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if bot_token and chat_id:
            return TelegramNotifier(bot_token, chat_id)
        logger.warning("Alerts disabled: Telegram credentials are incomplete")
        return None

    logger.warning("Alerts disabled: unsupported ALERT_PROVIDER=%s", provider)
    return None


class AlertStateMachine:
    """Notify once after sustained failure, then once when it recovers."""

    def __init__(self, state_path: Path, notifier: Notifier | None = None):
        self.state_path = Path(state_path)
        self.notifier = notifier
        self._state = self._load()

    def record_failure(self, reason: str) -> None:
        """Record a failed poll and alert only when the threshold is crossed."""
        failures = min(self._state["consecutive_failures"] + 1, FAILURE_THRESHOLD)
        self._state["consecutive_failures"] = failures

        if failures < FAILURE_THRESHOLD:
            logger.warning("Poll failure %d/%d: %s", failures, FAILURE_THRESHOLD, reason)
            self._save()
            return

        if self._state["failure_alerted"]:
            logger.warning("Poll remains failed after alert: %s", reason)
            return

        # Persist before delivery so a restart cannot repeat an unchanged alert.
        self._state["failure_alerted"] = True
        self._save()
        self._send("failure", "Bitget Tracker alert: polling has failed 3 consecutive times.")

    def record_success(self) -> None:
        """Clear a failure episode and send one recovery alert when needed."""
        was_alerted = self._state["failure_alerted"]
        if not self._state["consecutive_failures"] and not was_alerted:
            return

        self._state = {"consecutive_failures": 0, "failure_alerted": False}
        # Persist before delivery so recovery is also one-shot across restarts.
        self._save()
        if was_alerted:
            self._send("recovery", "Bitget Tracker recovery: polling is healthy again.")

    def _send(self, event: str, message: str) -> None:
        if self.notifier is None:
            logger.warning("Alert event=%s was not delivered: no provider configured", event)
            return
        try:
            self.notifier.send(event, message)
        except Exception as error:  # Alert delivery must never stop polling.
            logger.warning("Alert delivery failed for event=%s (%s)", event, type(error).__name__)

    def _load(self) -> dict[str, int | bool]:
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"consecutive_failures": 0, "failure_alerted": False}
        if not isinstance(saved, dict):
            return {"consecutive_failures": 0, "failure_alerted": False}
        try:
            failures = min(max(int(saved.get("consecutive_failures", 0)), 0), FAILURE_THRESHOLD)
        except (TypeError, ValueError):
            return {"consecutive_failures": 0, "failure_alerted": False}
        return {
            "consecutive_failures": failures,
            "failure_alerted": failures == FAILURE_THRESHOLD and saved.get("failure_alerted") is True,
        }

    def _save(self) -> None:
        payload = json.dumps(self._state, sort_keys=True)
        temporary_name: str | None = None
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.state_path.parent,
                prefix=f".{self.state_path.name}.", suffix=".tmp", delete=False,
            ) as temporary:
                temporary.write(payload)
                temporary.flush()
                temporary_name = temporary.name
            os.replace(temporary_name, self.state_path)
        except OSError as error:
            logger.warning("Could not persist alert state (%s)", type(error).__name__)
        finally:
            if temporary_name:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass
