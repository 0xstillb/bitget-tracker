from pathlib import Path


SCRIPT = Path("esp32/bitget_cyd/provision-wifi.ps1")


def test_windows_provisioning_uses_the_serial_type_built_into_windows_powershell():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "System.IO.Ports.SerialPort" in source
    assert "Add-Type -AssemblyName System.IO.Ports" not in source
