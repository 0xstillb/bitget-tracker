"""Versioned, secret-free snapshots of the tracker viewer state."""

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SNAPSHOT_VERSION = 1
_SECRET_MARKERS = (
    "api_key", "authorization", "cookie", "credential", "local_storage",
    "passphrase", "password", "secret", "token",
)
_PRESERVE_LAST_GOOD_STATES = {"expired", "transient"}


def _is_secret_key(key: object) -> bool:
    normalized = str(key).lower()
    return any(marker in normalized for marker in _SECRET_MARKERS)


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize(item)
            for key, item in value.items()
            if not _is_secret_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


class SnapshotStore:
    """Atomically save and load the last safe viewer snapshot."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict | None:
        try:
            snapshot = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(snapshot, dict) or snapshot.get("version") != SNAPSHOT_VERSION:
            return None
        if not isinstance(snapshot.get("data"), dict) or not isinstance(snapshot.get("updated_at"), str):
            return None
        return {
            "version": SNAPSHOT_VERSION,
            "updated_at": snapshot["updated_at"],
            "data": _normalize(snapshot["data"]),
        }

    def save(self, data: dict, session_state: str | None = None) -> bool:
        """Save an atomic normalized snapshot, retaining last-good on known failures."""
        if session_state in _PRESERVE_LAST_GOOD_STATES or not isinstance(data, dict):
            return False

        snapshot = {
            "version": SNAPSHOT_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "data": _normalize(data),
        }
        encoded = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
                temp_name = temporary.name
            os.replace(temp_name, self.path)
            return True
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
