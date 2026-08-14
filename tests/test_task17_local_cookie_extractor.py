import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "chrome-extension"


def test_extension_is_manifest_v3_and_scoped_to_bitget_only():
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 3
    assert manifest["permissions"] == ["cookies", "clipboardWrite"]
    assert manifest["host_permissions"] == ["https://*.bitget.com/*"]
    assert "storage" not in manifest["permissions"]
    assert "tabs" not in manifest["permissions"]
    assert "scripting" not in manifest["permissions"]


def test_popup_copies_only_a_complete_bitget_session_without_persisting_or_sending_it():
    popup = (EXTENSION / "popup.js").read_text(encoding="utf-8")

    assert "chrome.cookies.getAll" in popup
    assert "bt_newsessionid" in popup
    assert "navigator.clipboard.writeText" in popup
    assert "chrome.storage" not in popup
    assert "fetch(" not in popup
    assert "XMLHttpRequest" not in popup
    assert "WebSocket" not in popup


def test_extension_documents_local_only_install_and_secret_handling():
    guide = (EXTENSION / "README.md").read_text(encoding="utf-8")

    assert "Developer mode" in guide
    assert "never sends" in guide
    assert "never stores" in guide
    assert "bt_newsessionid" in guide
