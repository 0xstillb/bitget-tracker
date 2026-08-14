from pathlib import Path


MOCKUP = Path("esp32/bitget_cyd/ui-mockup.html")


def test_mockup_targets_the_cyd_screen_and_keeps_the_dashboard_hierarchy():
    source = MOCKUP.read_text(encoding="utf-8")

    assert "320 by 240" in source
    for label in ("TOTAL EQUITY", "TODAY P&amp;L", "OPEN P&amp;L", "ALL-TIME", "OPEN POSITIONS"):
        assert label in source


def test_mockup_provides_reviewable_connection_and_position_states():
    source = MOCKUP.read_text(encoding="utf-8")

    for state in ("LIVE", "STALE", "OFFLINE", "POSITION SAMPLE"):
        assert f'data-state="{state.lower().replace(" ", "-")}"' in source or state in source
    assert "Wi-Fi connected" in source
    assert "touch to refresh" in source
