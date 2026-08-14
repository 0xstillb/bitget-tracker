from pathlib import Path


FIRMWARE = Path("esp32/bitget_cyd/bitget_cyd.ino")


def test_320x240_dashboard_preserves_the_mockup_section_order_and_four_cards():
    source = FIRMWARE.read_text(encoding="utf-8")

    for required in (
        'drawMetricFrame(5, "TODAY P&L")',
        'drawMetricFrame(83, "OPEN P&L")',
        'drawMetricFrame(161, "ALL-TIME P&L")',
        'drawMetricFrame(239, "OPEN POSITIONS")',
        'tft.fillRoundRect(5, 130, 310, 43, 7, COLOR_PANEL)',
        'tft.fillRoundRect(5, 178, 310, 43, 7, COLOR_PANEL)',
        'tft.drawString("OPEN POSITIONS", 13, 136, 1)',
        'tft.drawString("TRACKED PORTFOLIOS", 13, 184, 1)',
    ):
        assert required in source


def test_dashboard_uses_mockup_style_hero_and_live_auth_pill_without_a_fake_chart():
    source = FIRMWARE.read_text(encoding="utf-8")

    assert "static const uint16_t COLOR_BACKGROUND = TFT_BLACK;" in source
    assert "tft.fillRoundRect(218, 12, 89, 17, 9" in source
    assert "TOTAL EQUITY" in source
    assert 'String("Updated ") + compactUpdated(lastUpdated)' in source
    assert "drawEquityHistory" not in source


def test_mockup_fidelity_keeps_partial_redraw_for_the_flicker_fix():
    source = FIRMWARE.read_text(encoding="utf-8")

    render_body = source.split("static void renderDashboard()", 1)[1].split("static void loadConfiguration()", 1)[0]
    assert "tft.fillScreen" not in render_body
