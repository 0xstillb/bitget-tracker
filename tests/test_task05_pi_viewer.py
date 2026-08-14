import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from pi_viewer import CoreSnapshotClient, PiViewer, ViewerApplication, ViewerCache


@contextmanager
def viewer_directory():
    root = Path.cwd() / ".codex-tmp"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        yield Path(directory)


def snapshot(balance=12.5):
    return {
        "version": 1,
        "updated_at": "2026-08-13T14:00:00+00:00",
        "data": {"summary": {"total_balance": balance}, "traders": []},
    }


def test_cache_is_atomic_and_never_persists_secret_shaped_fields(monkeypatch):
    with viewer_directory() as directory:
        cache = ViewerCache(directory / "viewer-cache.json")
        calls = []
        real_replace = os.replace

        def tracking_replace(source, destination):
            calls.append((Path(source), Path(destination)))
            real_replace(source, destination)

        monkeypatch.setattr("pi_viewer.os.replace", tracking_replace)
        saved = cache.save({**snapshot(), "data": {"summary": {"total_balance": 12.5, "token": "no"}}})

        assert saved is True
        assert calls and calls[0][1] == directory / "viewer-cache.json"
        assert cache.load()["data"] == {"summary": {"total_balance": 12.5}}


def test_transient_core_failure_keeps_last_good_cache_and_sets_backoff():
    class FailingClient:
        def fetch(self):
            raise TimeoutError("core timed out")

    with viewer_directory() as directory:
        cache = ViewerCache(directory / "viewer-cache.json")
        cache.save(snapshot(balance=10))
        viewer = PiViewer(FailingClient(), cache, clock=lambda: 100.0)

        assert viewer.refresh_once() is False
        assert viewer.summary()["data"]["summary"]["total_balance"] == 10
        assert viewer.health()["backoff_seconds"] == 1
        assert viewer.health()["last_error"] == "core timed out"


def test_successful_fetch_updates_the_cached_snapshot():
    class Client:
        def fetch(self):
            return snapshot(balance=25)

    with viewer_directory() as directory:
        viewer = PiViewer(Client(), ViewerCache(directory / "viewer-cache.json"), clock=lambda: 100.0)

        assert viewer.refresh_once() is True
        assert viewer.summary()["data"]["summary"]["total_balance"] == 25
        assert viewer.health()["last_error"] is None


def test_http_application_is_get_only_with_required_routes():
    class Client:
        def fetch(self):
            return snapshot()

    with viewer_directory() as directory:
        viewer = PiViewer(Client(), ViewerCache(directory / "viewer-cache.json"), clock=lambda: 100.0)
        app = ViewerApplication(viewer)

        assert app.response("GET", "/")[0] == 200
        status, _headers, body = app.response("GET", "/api/v1/summary")
        assert status == 200
        assert json.loads(body)["data"]["summary"]["total_balance"] == 12.5
        assert app.response("GET", "/api/v1/health")[0] == 200
        assert app.response("POST", "/api/v1/summary")[0] == 405
        assert app.response("GET", "/not-found")[0] == 404


def test_core_client_sends_only_the_internal_token_header(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(snapshot()).encode()

    class Opener:
        def open(self, request, timeout):
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return Response()

    monkeypatch.setattr("pi_viewer.build_opener", lambda *_handlers: Opener())
    result = CoreSnapshotClient("http://100.64.0.1:10000/internal/v1/snapshot", "viewer-token", timeout=3).fetch()

    assert result["version"] == 1
    assert captured["headers"]["X-internal-token"] == "viewer-token"
    assert captured["timeout"] == 3


def test_viewer_has_no_browser_or_bitget_secret_dependencies():
    source = Path("pi_viewer.py").read_text(encoding="utf-8").lower()

    assert "playwright" not in source
    assert "bitget_cookie" not in source
    assert "api_secret" not in source


def test_pi_deployment_example_is_read_only_and_uses_private_core():
    env_example = Path("deploy/pi-viewer.env.example").read_text(encoding="utf-8")
    service = Path("deploy/bitget-pi-viewer.service.example").read_text(encoding="utf-8")

    assert "CORE_SNAPSHOT_URL=http://100.64." in env_example
    assert "INTERNAL_API_TOKEN=" in env_example
    assert "PI_VIEWER_CACHE_PATH=/var/lib/bitget-pi-viewer/viewer-cache.json" in service
