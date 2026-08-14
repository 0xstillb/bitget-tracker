import shutil
import subprocess

from pi_viewer import DASHBOARD_JS


def test_pi_dashboard_script_parses_in_supported_browser_javascript():
    node = shutil.which("node")
    assert node, "Node.js is required to syntax-check the dashboard script"

    result = subprocess.run(
        [node, "--check", "-"],
        input=DASHBOARD_JS,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
