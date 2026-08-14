import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import login_protocol


NODE = shutil.which("node")


def _run_worker(env=None):
    request = login_protocol.build_start_request("request-11", "challenge-11")
    process_env = os.environ.copy()
    process_env.update(env or {})
    completed = subprocess.run(
        [NODE, str(Path("headless/login-worker.js").resolve())],
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        env=process_env,
        timeout=5,
        check=False,
    )
    return completed, [json.loads(line) for line in completed.stdout.splitlines()]


def _run_node(expression):
    completed = subprocess.run(
        [NODE, "-e", expression],
        input="",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )
    return json.loads(completed.stdout)


def test_auto_login_is_disabled_by_default_in_example_configuration():
    example = Path(".env.example").read_text(encoding="utf-8")

    assert "AUTO_LOGIN_ENABLED=false" in example


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_disabled_worker_stops_before_credentials_or_browser_are_needed():
    completed, events = _run_worker({
        "AUTO_LOGIN_ENABLED": "false",
        "BITGET_PHONE": "",
        "BITGET_PASSWORD": "",
    })

    assert completed.returncode == 0
    assert [(event["state"], event.get("code")) for event in events] == [
        ("started", None),
        ("failed", "disabled"),
    ]


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_enabled_worker_requires_worker_side_credentials_before_browser_start():
    completed, events = _run_worker({
        "AUTO_LOGIN_ENABLED": "true",
        "BITGET_PHONE": "",
        "BITGET_PASSWORD": "",
    })

    assert completed.returncode == 0
    assert [(event["state"], event.get("code")) for event in events] == [
        ("started", None),
        ("failed", "credentials_missing"),
    ]


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_attempts_and_timeout_are_bounded():
    result = _run_node("""
      const { readConfig } = require('./headless/login-worker.js');
      process.stdout.write(JSON.stringify({
        defaults: readConfig({}),
        high: readConfig({AUTO_LOGIN_ENABLED: 'true', AUTO_LOGIN_MAX_ATTEMPTS: '99', AUTO_LOGIN_TIMEOUT_SEC: '9999'}),
        low: readConfig({AUTO_LOGIN_ENABLED: 'true', AUTO_LOGIN_MAX_ATTEMPTS: '0', AUTO_LOGIN_TIMEOUT_SEC: '1'})
      }));
    """)

    assert result["defaults"] == {"enabled": False, "maxAttempts": 2, "timeoutMs": 180_000}
    assert result["high"] == {"enabled": True, "maxAttempts": 3, "timeoutMs": 300_000}
    assert result["low"] == {"enabled": True, "maxAttempts": 1, "timeoutMs": 30_000}


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_worker_stops_after_bounded_attempts_and_reports_timeout():
    result = _run_node("""
      const { runRequest } = require('./headless/login-worker.js');
      const events = [];
      let attempts = 0;
      const request = {version: 1, action: 'start', request_id: 'r11', challenge: 'c11'};
      (async () => {
        await runRequest(request, {
          AUTO_LOGIN_ENABLED: 'true',
          AUTO_LOGIN_MAX_ATTEMPTS: '99',
          AUTO_LOGIN_TIMEOUT_SEC: '30',
          BITGET_PHONE: 'worker-only-user',
          BITGET_PASSWORD: 'worker-only-password'
        }, {
          attemptLogin: async () => { attempts += 1; return {state: 'timeout', code: 'attempts_exhausted'}; },
          emit: (_request, state, code) => events.push({state, ...(code ? {code} : {})})
        });
        process.stdout.write(JSON.stringify({attempts, events}));
      })().catch(error => { process.stderr.write(error.stack); process.exit(1); });
    """)

    assert result == {
        "attempts": 3,
        "events": [
            {"state": "started"},
            {"state": "timeout", "code": "attempts_exhausted"},
        ],
    }


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_login_page_states_are_detected_without_security_bypass():
    result = _run_node("""
      const { classifyLoginSnapshot } = require('./headless/login-worker.js');
      const classify = snapshot => classifyLoginSnapshot({url: 'https://www.bitget.com/login', selectors: [], text: '', authenticated: false, ...snapshot});
      process.stdout.write(JSON.stringify({
        approval: classify({text: 'Check your Bitget app and approve this login'}),
        otp: classify({selectors: ['input[autocomplete="one-time-code"]'], text: 'Enter verification code'}),
        captcha: classify({selectors: ['iframe[src*="captcha"]'], text: 'Verify you are human'}),
        rejected: classify({text: 'Login rejected. Incorrect password.'}),
        success: classify({url: 'https://www.bitget.com/account', authenticated: true}),
        pending: classify({text: 'Welcome back'})
      }));
    """)

    assert result == {
        "approval": {"state": "approval_required", "code": "approval_pending"},
        "otp": {"state": "otp_required", "code": "otp_pending"},
        "captcha": {"state": "captcha_required", "code": "captcha_pending"},
        "rejected": {"state": "failed", "code": "rejected"},
        "success": {"state": "success"},
        "pending": None,
    }


def test_worker_contains_no_otp_captcha_or_trade_execution_automation():
    source = Path("headless/login-worker.js").read_text(encoding="utf-8").lower()

    assert "bitget_otp" not in source
    assert "captcha_token" not in source
    assert "solvecaptcha" not in source
    for forbidden in ("placeorder", "place_order", "closeposition", "cancelorder", "modify_sl"):
        assert forbidden not in source
