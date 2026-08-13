"""A lightweight, GET-only Pi Viewer for the private Core snapshot API."""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlsplit


_SECRET_MARKERS = (
    "api_key", "authorization", "cookie", "credential", "local_storage",
    "passphrase", "password", "secret", "token",
)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if not any(marker in str(key).lower() for marker in _SECRET_MARKERS)
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _normalize_snapshot(snapshot: Any) -> dict | None:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("data"), dict):
        return None
    if not isinstance(snapshot.get("version"), int) or not isinstance(snapshot.get("updated_at"), str):
        return None
    return {
        "version": snapshot["version"],
        "updated_at": snapshot["updated_at"],
        "data": _sanitize(snapshot["data"]),
    }


class ViewerCache:
    """Secret-free local cache, updated atomically to preserve last-good data."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict | None:
        try:
            return _normalize_snapshot(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, snapshot: dict) -> bool:
        normalized = _normalize_snapshot(snapshot)
        if normalized is None:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as temporary:
                temporary.write(json.dumps(normalized, separators=(",", ":"), ensure_ascii=False))
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, self.path)
            return True
        finally:
            if temporary_name:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass


class CoreSnapshotClient:
    """Fetch only the Core's read-only snapshot using the Pi's internal token."""

    def __init__(self, url: str, token: str, timeout: float = 5.0):
        self.url = url
        self.token = token
        self.timeout = timeout

    def fetch(self) -> dict:
        if not self.url or not self.token:
            raise RuntimeError("Core snapshot URL or internal token is not configured")
        request = Request(self.url, headers={"X-Internal-Token": self.token, "Accept": "application/json"})
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - URL is operator configuration
            snapshot = json.loads(response.read().decode("utf-8"))
        normalized = _normalize_snapshot(snapshot)
        if normalized is None:
            raise ValueError("Core returned an invalid snapshot")
        return normalized


class PiViewer:
    """Refresh Core data with bounded exponential backoff while serving cache."""

    def __init__(self, client: CoreSnapshotClient, cache: ViewerCache,
                 clock=time.monotonic, refresh_interval: float = 30.0):
        self.client = client
        self.cache = cache
        self.clock = clock
        self.refresh_interval = refresh_interval
        self.snapshot = cache.load()
        self.failures = 0
        self.next_attempt = 0.0
        self.last_error: str | None = None
        self.last_success_at: str | None = None

    def refresh_once(self) -> bool:
        now = self.clock()
        if now < self.next_attempt:
            return False
        try:
            snapshot = self.client.fetch()
            if not self.cache.save(snapshot):
                raise ValueError("Core returned an invalid snapshot")
            self.snapshot = snapshot
            self.failures = 0
            self.next_attempt = now + self.refresh_interval
            self.last_error = None
            self.last_success_at = datetime.now(timezone.utc).isoformat()
            return True
        except Exception as error:
            self.failures += 1
            backoff = min(300, 2 ** (self.failures - 1))
            self.next_attempt = now + backoff
            self.last_error = str(error)
            return False

    def summary(self) -> dict | None:
        self.refresh_once()
        return self.snapshot

    def health(self) -> dict:
        return {
            "ok": self.snapshot is not None,
            "cached": self.snapshot is not None,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "backoff_seconds": min(300, 2 ** (self.failures - 1)) if self.failures else 0,
        }

    def esp32_home(self) -> dict | None:
        """Project cached Core snapshot into the established compact ESP32 schema."""
        snapshot = self.summary()
        if snapshot is None:
            return None
        data = snapshot["data"]
        summary = data.get("summary") or {}
        earn = data.get("earn") or {}
        elite = data.get("elite") or {"on": False, "bal": 0.0}
        positions = list(data.get("positions") or [])[:3]
        traders = []
        for trader in data.get("traders") or []:
            if not isinstance(trader, dict) or not trader.get("has_data", True):
                continue
            traders.append({
                "n": str(trader.get("name") or "")[:16],
                "bal": round(trader.get("balance") or 0.0, 2),
                "day": round(trader.get("daily_pnl") or 0.0, 2),
                "all": round(trader.get("all_time_pnl") or 0.0, 2),
                "open": round(trader.get("open_positions_pnl") or 0.0, 2),
                "pos": int(trader.get("open_position_count") or 0),
            })
        return {
            "ok": True,
            "stale": self.last_error is not None,
            "upd": summary.get("pushed_at") or snapshot["updated_at"],
            "bal": round((summary.get("total_balance") or 0.0) + (earn.get("total") or 0.0) + (elite.get("bal") or 0.0), 2),
            "inv": round(summary.get("total_investment") or 0.0, 2),
            "day": round(summary.get("daily_pnl") or 0.0, 2),
            "open": round(summary.get("open_positions_pnl") or 0.0, 2),
            "npos": int(summary.get("open_positions") or 0),
            "ntoday": int(summary.get("trades_today") or 0),
            "all": round(summary.get("all_time_pnl") or 0.0, 2),
            "earn": round(earn.get("total") or 0.0, 2),
            "eday": round(earn.get("interest_24h") or 0.0, 2),
            "traders": traders,
            "elite": elite,
            "positions": positions,
        }

    def esp32_positions(self) -> list[dict]:
        snapshot = self.summary()
        return list((snapshot or {"data": {}})["data"].get("positions") or [])

    def esp32_history(self, limit: int) -> list[dict]:
        snapshot = self.summary()
        history = list((snapshot or {"data": {}})["data"].get("history") or [])
        return history[:max(1, min(limit, 100))]


class ViewerApplication:
    """Route the intentionally small GET-only HTTP surface."""

    def __init__(self, viewer: PiViewer):
        self.viewer = viewer

    def response(self, method: str, path: str) -> tuple[int, dict[str, str], str]:
        if method != "GET":
            return 405, {"Allow": "GET", "Content-Type": "application/json"}, json.dumps({"detail": "GET only"})
        parsed = urlsplit(path)
        route = parsed.path
        if route == "/":
            return 200, {"Content-Type": "text/html; charset=utf-8"}, (
                "<!doctype html><title>Bitget Pi Viewer</title><h1>Bitget Pi Viewer</h1>"
                "<p>Read-only cached snapshot service.</p>"
            )
        if route == "/api/v1/summary":
            snapshot = self.viewer.summary()
            if snapshot is None:
                return 503, {"Content-Type": "application/json"}, json.dumps({"detail": "no cached snapshot"})
            return 200, {"Content-Type": "application/json"}, json.dumps(snapshot)
        if route == "/api/v1/health":
            return 200, {"Content-Type": "application/json"}, json.dumps(self.viewer.health())
        if route == "/api/esp32":
            payload = self.viewer.esp32_home()
            if payload is None:
                return 503, {"Content-Type": "application/json"}, json.dumps({"detail": "no cached snapshot"})
            return 200, {"Content-Type": "application/json"}, json.dumps(payload)
        if route == "/api/esp32/positions":
            return 200, {"Content-Type": "application/json"}, json.dumps({"positions": self.viewer.esp32_positions()})
        if route == "/api/esp32/history":
            raw_limit = parse_qs(parsed.query).get("n", ["30"])[0]
            try:
                limit = int(raw_limit)
            except ValueError:
                limit = 30
            return 200, {"Content-Type": "application/json"}, json.dumps({"trades": self.viewer.esp32_history(limit)})
        return 404, {"Content-Type": "application/json"}, json.dumps({"detail": "not found"})


def make_handler(application: ViewerApplication):
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, method: str) -> None:
            status, headers, body = application.response(method, self.path)
            encoded = body.encode("utf-8")
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802
            self._respond("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._respond("POST")

        def do_PUT(self) -> None:  # noqa: N802
            self._respond("PUT")

        def do_PATCH(self) -> None:  # noqa: N802
            self._respond("PATCH")

        def do_DELETE(self) -> None:  # noqa: N802
            self._respond("DELETE")

        def log_message(self, _format: str, *_args) -> None:
            return

    return Handler


def run_from_env() -> None:
    client = CoreSnapshotClient(
        os.environ.get("CORE_SNAPSHOT_URL", ""),
        os.environ.get("INTERNAL_API_TOKEN", ""),
        timeout=float(os.environ.get("CORE_SNAPSHOT_TIMEOUT_SEC", "5")),
    )
    viewer = PiViewer(client, ViewerCache(Path(os.environ.get("PI_VIEWER_CACHE_PATH", "viewer-cache.json"))))
    application = ViewerApplication(viewer)

    def refresh_loop() -> None:
        while True:
            viewer.refresh_once()
            time.sleep(1)

    threading.Thread(target=refresh_loop, daemon=True).start()
    ThreadingHTTPServer((os.environ.get("PI_VIEWER_BIND_HOST", "0.0.0.0"),
                         int(os.environ.get("PI_VIEWER_PORT", "8080"))), make_handler(application)).serve_forever()


if __name__ == "__main__":
    run_from_env()
