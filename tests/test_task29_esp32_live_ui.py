from pathlib import Path


FIRMWARE = Path("esp32/bitget_cyd/bitget_cyd.ino")


def test_live_dashboard_redraws_dynamic_regions_without_clearing_the_entire_screen():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "static void drawDashboardChrome()" in source
    assert "static void renderDashboard()" in source
    render_body = source.split("static void renderDashboard()", 1)[1].split("static void loadConfiguration()", 1)[0]
    assert "tft.fillScreen" not in render_body


def test_touch_refresh_is_edge_triggered_and_debounced():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "TOUCH_DEBOUNCE_MS" in source
    assert "lastTouchAt" in source
    assert "touchDown && !touchWasDown" in source


def test_live_dashboard_reads_safe_auth_and_position_data_from_the_pi_viewer():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert '"/api/esp32"' in source
    assert '"/api/v1/auth"' in source
    assert "lastOpenPositionCount" in source
    assert "OPEN POSITIONS" in source
    assert "APPROVE" in source
