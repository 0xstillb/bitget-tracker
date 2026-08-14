from pathlib import Path


FIRMWARE = Path("esp32/bitget_cyd/bitget_cyd.ino")
README = Path("esp32/bitget_cyd/README.md")


def test_firmware_exposes_a_bounded_usb_provisioning_protocol():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "USB_PROVISIONING_WINDOW_MS" in source
    assert "SERIAL_LINE_MAX" in source
    assert '"set_wifi"' in source
    assert '"status"' in source
    assert '"reset"' in source
    assert "deserializeJson" in source


def test_provisioning_persists_wifi_and_viewer_url_without_echoing_password():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert 'preferences.putString("ssid"' in source
    assert 'preferences.putString("pass"' in source
    assert 'preferences.putString("url"' in source
    assert 'preferences.getString("ssid", "")' in source
    assert 'preferences.getString("pass", "")' in source
    assert 'preferences.getString("url", DEFAULT_VIEWER_URL)' in source
    assert 'request["password"]' in source
    assert 'Serial.println(request["password"]' not in source


def test_firmware_does_not_compile_wifi_credentials_from_a_source_file():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert '#include "secrets.h"' not in source
    assert "WIFI_SSID" not in source
    assert "WIFI_PASS" not in source


def test_readme_documents_usb_first_setup_and_secret_safety():
    readme = README.read_text(encoding="utf-8")

    assert "USB provisioning" in readme
    assert 'set_wifi' in readme
    assert "password" in readme
    assert "never commit" in readme.lower()
    assert "secrets.example.h" not in readme
