from pathlib import Path


SCRIPT = Path("esp32/bitget_cyd/provision-wifi.ps1")
README = Path("esp32/bitget_cyd/README.md")


def test_launcher_requires_a_fresh_manual_reset_before_sending_credentials():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "EN/RESET" in source
    assert "Read-Host" in source
    assert "Press Enter" in source


def test_setup_documentation_explains_the_fresh_boot_window():
    readme = README.read_text(encoding="utf-8")

    assert "EN/RESET" in readme
    assert "two-minute" in readme
