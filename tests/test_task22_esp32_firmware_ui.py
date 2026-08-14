from pathlib import Path


FIRMWARE = Path("esp32/bitget_cyd/bitget_cyd.ino")


def test_cyd_dashboard_has_a_compact_visual_system_for_the_320x240_screen():
    source = FIRMWARE.read_text(encoding="utf-8")

    for required in (
        "COLOR_BACKGROUND",
        "COLOR_PANEL",
        "COLOR_ACCENT",
        "drawMetricCard",
        "drawWideMetricCard",
        "drawMetricValue",
        "drawWidePositionValue",
        "OPEN P&L (now)",
        "OPEN POSITIONS",
        "ESP.getFreeHeap",
    ):
        assert required in source


def test_cyd_dashboard_keeps_live_position_and_pnl_values_separate_for_visual_formatting():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "lastOpenPositionCount" in source
    assert "lastOpenPnl" in source
    assert "pnlColor(lastOpenPnl)" in source
    assert 'http.GET()' in source
