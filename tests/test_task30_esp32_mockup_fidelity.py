from pathlib import Path


FIRMWARE = Path("esp32/bitget_cyd/bitget_cyd.ino")


def test_dashboard_matches_the_two_by_three_card_reference_layout():
    source = FIRMWARE.read_text(encoding="utf-8")

    for required in (
        'drawMetricCard(5, 5, "TOTAL BALANCE")',
        'drawMetricCard(163, 5, "TODAY P&L")',
        'drawMetricCard(5, 74, "OPEN P&L (now)")',
        'drawMetricCard(163, 74, "ALL-TIME P&L")',
        'drawWideMetricCard(5, 143, "OPEN POSITIONS")',
        "tft.fillRoundRect(x, y, 152, 64, 10, COLOR_PANEL)",
        "tft.fillRoundRect(x, y, 310, 64, 10, COLOR_PANEL)",
        "drawWidePositionValue();",
        "ESP.getFreeHeap() / 1024",
    ):
        assert required in source

    assert "TRACKED PORTFOLIOS" not in source
    assert "TODAY EARN" not in source
    assert "EARN BALANCE" not in source
    assert 'payload["eday"]' not in source
    assert 'payload["earn"]' not in source


def test_dashboard_shows_only_real_snapshot_values_and_no_fake_history():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert '"/api/esp32"' in source
    assert "lastOpenPnl" in source
    assert "lastTodayPnl" in source
    assert "lastEquity" in source
    assert "lastAllPnl" in source
    assert "lastOpenPositionCount" in source
    assert "drawEquityHistory" not in source


def test_reference_layout_keeps_partial_redraw_and_touch_debounce():
    source = FIRMWARE.read_text(encoding="utf-8")

    render_body = source.split("static void renderDashboard()", 1)[1].split("static void loadConfiguration()", 1)[0]
    assert "tft.fillScreen" not in render_body
    assert "touchDown && !touchWasDown" in source
