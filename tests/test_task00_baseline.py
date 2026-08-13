from pathlib import Path


BASELINE = Path(__file__).resolve().parents[1] / "TASK_00_BASELINE.md"


def test_task00_baseline_covers_required_audit_sections():
    report = BASELINE.read_text(encoding="utf-8")

    for section in (
        "## Repository and tests",
        "## Endpoint inventory",
        "## Secrets and state",
        "## Poller",
        "## ESP32",
        "## Deployment",
        "## Risks and follow-up boundaries",
    ):
        assert section in report


def test_task00_baseline_records_current_integration_facts():
    report = BASELINE.read_text(encoding="utf-8")

    assert "35 explicit API routes" in report
    assert "test_investment_api.py" in report
    assert "No product behavior changed" in report
