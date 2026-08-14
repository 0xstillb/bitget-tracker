from pathlib import Path


FIRMWARE = Path("esp32/bitget_cyd/bitget_cyd.ino")


def test_wifi_reconnect_is_rate_limited_instead_of_restarting_every_loop():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "WIFI_RETRY_INTERVAL_MS" in source
    assert "lastWifiAttemptAt" in source
    assert "now - lastWifiAttemptAt < WIFI_RETRY_INTERVAL_MS" in source
