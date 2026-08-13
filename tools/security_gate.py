"""Fail closed on repository-level security invariants for release review."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
FORBIDDEN_TRACKED_NAMES = {
    ".env", "cookies.json", "credentials.json", "secrets.h", "viewer-cache.json",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA) PRIVATE KEY-----"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def check_tracked_secrets() -> None:
    for relative in tracked_files():
        path = ROOT / relative
        if path.name in FORBIDDEN_TRACKED_NAMES or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            fail(f"runtime secret/state file is tracked: {relative}")
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            fail(f"secret pattern found in tracked file: {relative}")


def check_workflows() -> None:
    workflows = list(WORKFLOW_DIR.glob("*.yml"))
    if not workflows:
        fail("no GitHub Actions workflows found")
    for path in workflows:
        content = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^permissions:\s*\n\s+contents:\s*read\s*$", content):
            fail(f"workflow lacks read-only permissions: {path.name}")
        if "pull_request_target" in content:
            fail(f"unsafe pull_request_target trigger: {path.name}")
        for action in re.findall(r"uses:\s*([^\s#]+)", content):
            if not re.fullmatch(r"[^@]+@[0-9a-f]{40}", action):
                fail(f"workflow action is not SHA pinned: {path.name}: {action}")


def check_dependencies() -> None:
    lock = read("requirements.lock")
    if "--hash=sha256:" not in lock:
        fail("Python lock has no hashes")
    dev_lock = read("requirements-dev.lock")
    if "pytest==" not in dev_lock or "--hash=sha256:" not in dev_lock:
        fail("Python development lock must hash-pin pytest")
    dockerfile = read("Dockerfile")
    if "--require-hashes -r requirements.lock" not in dockerfile:
        fail("container does not enforce the hashed Python lock")
    package_lock = read("headless/package-lock.json")
    if '"lockfileVersion": 3' not in package_lock:
        fail("Node lockfile v3 is required")
    package = json.loads(read("headless/package.json"))
    requested_puppeteer = package["dependencies"]["puppeteer"].lstrip("^~>=< ")
    if int(requested_puppeteer.split(".", 1)[0]) < 25:
        fail("Puppeteer 25 or newer is required by the audited lock")
    if package.get("engines", {}).get("node") != ">=22.12.0":
        fail("Node engine must match the supported Puppeteer runtime")
    if "npm audit --omit=dev --audit-level=high" not in read(".github/workflows/security-gate.yml"):
        fail("security CI must reject high-severity Node advisories")


def check_exposure_and_xss() -> None:
    tunnel = read("deploy/cloudflared-config.example.yml")
    if "service: http://127.0.0.1:8080" not in tunnel or "10000" in tunnel:
        fail("Tunnel must expose only the loopback Pi Viewer")
    acl = read("deploy/tailscale-acl.example.hujson")
    required_grant = (
        '"grants"',
        '"src": ["tag:bitget-viewer"]',
        '"dst": ["tag:bitget-core"]',
        '"ip": ["tcp:10000"]',
    )
    if any(fragment not in acl for fragment in required_grant) or '"acls"' in acl:
        fail("Tailscale grants must allow only Viewer-to-Core TCP 10000")
    dashboard = read("static/index.html")
    for fragment in ("${p.symbol}", "${t.symbol}", "${it.coin}", "${res.error || 'unknown'}"):
        if fragment in dashboard:
            fail(f"unescaped dashboard interpolation remains: {fragment}")


def main() -> int:
    try:
        check_tracked_secrets()
        check_workflows()
        check_dependencies()
        check_exposure_and_xss()
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        print(f"security gate failed: {error}", file=sys.stderr)
        return 1
    print("Security gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
