from pathlib import Path


BASELINE = Path(__file__).resolve().parents[1] / "TASK_00_BASELINE.md"


def test_task00_baseline_covers_required_audit_sections():
    report = BASELINE.read_text(encoding="utf-8")
    required_sections = (
        "## Repository and tests",
        "## Endpoint inventory",
        "## Secrets and state",
        "## Poller",
        "## ESP32",
        "## Deployment",
        "## Risks and follow-up boundaries",
    )

    for section in required_sections:
        assert section in report


def test_task00_baseline_records_no_behavior_change_and_test_baseline():
    report = BASELINE.read_text(encoding="utf-8")
    assert "No product behavior changed" in report
    assert "No pre-existing automated tests were found" in report
    assert "35 explicit API routes" in report
