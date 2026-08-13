import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from snapshot_store import SNAPSHOT_VERSION, SnapshotStore
import main


@contextmanager
def snapshot_directory():
    root = Path.cwd() / ".codex-tmp"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        yield Path(directory)


def test_saves_a_versioned_normalized_snapshot_without_secret_fields():
    with snapshot_directory() as directory:
        store = SnapshotStore(directory / "snapshot.json")

        saved = store.save({
            "summary": {"total_balance": 12.5},
            "nested": {"cookie": "must-not-persist", "token": "must-not-persist", "ok": True},
        })

        assert saved is True
        snapshot = store.load()
        assert snapshot["version"] == SNAPSHOT_VERSION
        assert snapshot["data"] == {"summary": {"total_balance": 12.5}, "nested": {"ok": True}}


def test_transient_or_expired_state_keeps_the_last_good_snapshot():
    with snapshot_directory() as directory:
        store = SnapshotStore(directory / "snapshot.json")
        assert store.save({"summary": {"total_balance": 10}}, session_state="valid") is True

        assert store.save({"summary": {"total_balance": 0}}, session_state="transient") is False
        assert store.save({"summary": {"total_balance": 0}}, session_state="expired") is False

        assert store.load()["data"]["summary"]["total_balance"] == 10


def test_uses_os_replace_for_atomic_snapshot_persistence(monkeypatch):
    with snapshot_directory() as directory:
        store = SnapshotStore(directory / "snapshot.json")
        replaced = []
        real_replace = os.replace

        def tracking_replace(source, destination):
            replaced.append((Path(source), Path(destination)))
            real_replace(source, destination)

        monkeypatch.setattr("snapshot_store.os.replace", tracking_replace)

        assert store.save({"summary": {"total_balance": 99}}) is True
        assert replaced and replaced[0][1] == directory / "snapshot.json"
        assert store.load()["data"]["summary"]["total_balance"] == 99


def test_invalid_or_unknown_snapshot_is_not_loaded():
    with snapshot_directory() as directory:
        path = directory / "snapshot.json"
        path.write_text('{"version": 999, "data": {}}', encoding="utf-8")

        assert SnapshotStore(path).load() is None


def test_runtime_snapshot_file_is_not_tracked():
    ignored = Path(".gitignore").read_text(encoding="utf-8")

    assert "snapshot.json" in ignored


def test_main_persists_only_the_normalized_viewer_summary(monkeypatch):
    recorded = {}

    class Store:
        def save(self, data, session_state=None):
            recorded["data"] = data
            recorded["session_state"] = session_state
            return True

    monkeypatch.setattr(main, "SNAPSHOT_STORE", Store())
    monkeypatch.setattr(main, "_mt5", {"summary": {"total_balance": 12.5}, "positions_raw": {"cookie": "nope"}})
    monkeypatch.setattr(main, "_traders_list", [{"name": "alpha", "id": "1", "type": "cfd"}])
    monkeypatch.setattr(main, "_traders_cache", {
        "alpha": {"summary": {"name": "alpha", "balance": 12.5}, "history_raw": {"token": "nope"}},
    })
    monkeypatch.setattr(main, "_snapshot_session_state", lambda: "valid")

    assert main._persist_snapshot() is True
    assert recorded["session_state"] == "valid"
    assert recorded["data"]["summary"] == {"total_balance": 12.5}
    assert recorded["data"]["traders"] == [{"name": "alpha", "balance": 12.5}]
    assert recorded["data"]["positions"] == []
    assert recorded["data"]["history"] == []
