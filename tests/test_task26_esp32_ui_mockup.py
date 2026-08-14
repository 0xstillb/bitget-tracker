from pathlib import Path


MOCKUP = Path("esp32/bitget_cyd/ui-mockup.html")


def test_mockup_targets_the_cyd_screen_and_keeps_the_dashboard_hierarchy():
    source = MOCKUP.read_text(encoding="utf-8")

    assert "320 by 240" in source
    assert "data:font/ttf;base64," in source
    assert "___NOTO_" not in source
    for label in ("TOTAL EQUITY", "Today P&amp;L", "Open P&amp;L", "All-time P&amp;L", "Open positions"):
        assert label in source


def test_mockup_provides_reviewable_connection_and_position_states():
    source = MOCKUP.read_text(encoding="utf-8")

    for state in ("AUTH UNKNOWN", "AUTHENTICATED", "APP APPROVAL REQUIRED", "LOGIN FAILED"):
        assert state in source
    assert "Tracked portfolios" in source
    assert "No active data" in source


def test_mockup_does_not_claim_static_pixels_are_a_live_equity_history():
    source = MOCKUP.read_text(encoding="utf-8")

    assert "Equity trend" not in source
    assert 'class="chart-line"' not in source
    assert 'class="chart-fill"' not in source


def test_mockup_reads_live_pi_viewer_data_instead_of_shipping_sample_values():
    source = MOCKUP.read_text(encoding="utf-8")

    assert "fetch('/api/v1/summary'" in source
    assert "fetch('/api/v1/auth'" in source
    assert "$652.48" not in source
    assert "+$6.65" not in source
    assert 'data-login="' not in source
