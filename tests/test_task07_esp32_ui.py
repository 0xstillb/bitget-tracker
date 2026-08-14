from pathlib import Path


FIRMWARE = Path("esp32/bitget_cyd/bitget_cyd.ino")


def test_cyd_firmware_keeps_the_required_hardware_stack_and_landscape_geometry():
    source = FIRMWARE.read_text(encoding="utf-8")

    for include in ("WiFi.h", "Preferences.h", "lvgl.h", "TFT_eSPI.h", "XPT2046_Touchscreen.h", "ArduinoJson.h"):
        assert include in source
    assert "SCREEN_WIDTH = 320" in source
    assert "SCREEN_HEIGHT = 240" in source
    assert "tft.setRotation(1)" in source


def test_cyd_ui_fetches_compact_pi_payloads_and_keeps_last_values():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert '"/api/esp32"' in source
    assert "lastEquity" in source
    assert "lastTodayPnl" in source
    assert "lastOpenPnl" in source
    assert '"/api/v1/auth"' in source
    assert "lastPositions[2]" in source
    assert "lastPortfolioName" in source
    assert "if (!payload[\"ok\"].as<bool>()) return false;" in source


def test_cyd_ui_has_mockup_style_status_pnl_equity_and_compact_position_layout():
    source = FIRMWARE.read_text(encoding="utf-8")

    for label in ("TOTAL EQUITY", "TODAY", "OPEN", "ALL-TIME", "OPEN POSITIONS", "TRACKED PORTFOLIO", "LIVE", "OFFLINE"):
        assert label in source
    assert "for (int index = 0; index < 2; ++index)" in source


def test_cyd_ui_uses_tft_espi_compatible_right_aligned_text_calls():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "tft.drawRightString(equity, 305, 39, 4);" in source
    assert '"TAP: REFRESH"' in source
    assert '"Wi-Fi reconnecting"' in source
    assert '"USB: setup"' in source


def test_cyd_templates_contain_no_real_wifi_or_service_secret():
    template = Path("esp32/bitget_cyd/secrets.example.h").read_text(encoding="utf-8")

    assert "YOUR_WIFI_SSID" in template
    assert "YOUR_WIFI_PASSWORD" in template
    assert "secrets.h" in Path(".gitignore").read_text(encoding="utf-8")


def test_cyd_has_a_reproducible_platformio_build_configuration():
    config = Path("esp32/bitget_cyd/platformio.ini").read_text(encoding="utf-8")

    assert "platform = espressif32" in config
    assert "board = esp32dev" in config
    assert "TFT_eSPI" in config
    assert "XPT2046_Touchscreen" in config
    assert "-D USER_SETUP_LOADED" in config
    assert "-include User_Setup.h" in config
    assert ".pio/" in Path(".gitignore").read_text(encoding="utf-8")


def test_cyd_tft_setup_loads_the_fonts_used_by_the_dashboard():
    setup = Path("esp32/bitget_cyd/User_Setup.h").read_text(encoding="utf-8")

    assert "#define LOAD_GLCD" in setup
    assert "#define LOAD_FONT2" in setup
