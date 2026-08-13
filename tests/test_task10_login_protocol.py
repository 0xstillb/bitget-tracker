import asyncio
import json
import shutil
from pathlib import Path

import pytest

import login_protocol


def _event(state, *, request_id="request-1", challenge="challenge-1", code=None):
    event = {
        "version": 1,
        "request_id": request_id,
        "challenge": challenge,
        "state": state,
    }
    if code is not None:
        event["code"] = code
    return event


def test_start_request_contains_no_credentials_or_free_form_payload():
    request = login_protocol.build_start_request("request-1", "challenge-1")

    assert request == {
        "version": 1,
        "action": "start",
        "request_id": "request-1",
        "challenge": "challenge-1",
    }
    serialized = json.dumps(request).lower()
    for forbidden in ("password", "phone", "email", "otp", "cookie", "secret"):
        assert forbidden not in serialized


def test_protocol_exposes_only_the_required_worker_states():
    assert login_protocol.WORKER_STATES == frozenset({
        "started",
        "approval_required",
        "otp_required",
        "captcha_required",
        "success",
        "failed",
        "timeout",
        "busy",
    })


def test_worker_events_are_bound_to_the_request_and_reject_extra_fields():
    event = login_protocol.parse_worker_event(
        json.dumps(_event("started")),
        expected_request_id="request-1",
        expected_challenge="challenge-1",
    )
    assert event.state == "started"

    with pytest.raises(login_protocol.LoginProtocolError):
        login_protocol.parse_worker_event(
            json.dumps(_event("started", challenge="wrong")),
            expected_request_id="request-1",
            expected_challenge="challenge-1",
        )
    leaked = _event("failed", code="worker_error")
    leaked["password"] = "must-not-cross-boundary"
    with pytest.raises(login_protocol.LoginProtocolError):
        login_protocol.parse_worker_event(
            json.dumps(leaked),
            expected_request_id="request-1",
            expected_challenge="challenge-1",
        )


def test_state_machine_rejects_out_of_order_or_post_terminal_events():
    session = login_protocol.LoginProtocolSession("request-1", "challenge-1")
    with pytest.raises(login_protocol.LoginProtocolError):
        session.accept(_event("success"))

    session.accept(_event("started"))
    session.accept(_event("approval_required", code="approval_pending"))
    session.accept(_event("otp_required", code="otp_pending"))
    terminal = session.accept(_event("success"))
    assert terminal.state == "success"

    with pytest.raises(login_protocol.LoginProtocolError):
        session.accept(_event("failed", code="worker_error"))


def test_core_downgrades_worker_success_when_canonical_verification_fails():
    async def rejected_verifier():
        return False

    result = asyncio.run(login_protocol.verify_terminal_result(
        login_protocol.LoginEvent("success"), rejected_verifier
    ))
    assert result == login_protocol.LoginResult("failed", "verification_failed")


def test_core_accepts_worker_success_only_after_canonical_verification():
    calls = []

    async def accepted_verifier():
        calls.append("verified")
        return True

    result = asyncio.run(login_protocol.verify_terminal_result(
        login_protocol.LoginEvent("success"), accepted_verifier
    ))
    assert result == login_protocol.LoginResult("success", None)
    assert calls == ["verified"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_node_worker_implements_the_same_credential_free_stdio_protocol():
    source = Path("headless/login-worker.js").read_text(encoding="utf-8")

    assert "process.stdin" in source
    assert "process.stdout.write" in source
    request_source = Path("login_protocol.py").read_text(encoding="utf-8")
    assert '"password"' not in request_source
    assert '"phone"' not in request_source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_core_and_node_worker_exchange_bound_events_over_local_stdio(monkeypatch):
    monkeypatch.setenv("AUTO_LOGIN_ENABLED", "false")
    events = []
    client = login_protocol.LoginWorkerClient(
        (shutil.which("node"), str(Path("headless/login-worker.js").resolve())),
        timeout_seconds=5,
    )

    result = asyncio.run(client.run(lambda: True, events.append))

    assert events == [
        login_protocol.LoginEvent("started"),
        login_protocol.LoginEvent("failed", "disabled"),
    ]
    assert result == login_protocol.LoginResult("failed", "disabled")
