from pathlib import Path


ROOT = Path("esp32/bitget_cyd")
BAT = ROOT / "provision-wifi.bat"
SCRIPT = ROOT / "provision-wifi.ps1"


def test_windows_launcher_starts_the_local_provisioning_ui():
    launcher = BAT.read_text(encoding="utf-8")

    assert "provision-wifi.ps1" in launcher
    assert "ExecutionPolicy Bypass" in launcher
    assert "pause" in launcher.lower()


def test_provisioning_ui_lists_ports_hides_password_and_sends_one_json_line():
    script = SCRIPT.read_text(encoding="utf-8")

    for required in (
        "GetPortNames",
        "Read-Host",
        "AsSecureString",
        "System.IO.Ports.SerialPort",
        "ConvertTo-Json -Compress",
        "WriteLine",
        "115200",
        "None",
    ):
        assert required in script
    assert "Write-Host $password" not in script
    assert "Write-Output $password" not in script


def test_readme_points_users_to_the_double_click_launcher():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "provision-wifi.bat" in readme
    assert "double-click" in readme.lower()
