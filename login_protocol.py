"""Credential-free, local stdio protocol between Core and the login worker."""

from __future__ import annotations

import asyncio
import hmac
import inspect
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Sequence


PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 4096
WORKER_STATES = frozenset({
    "started",
    "approval_required",
    "otp_required",
    "captcha_required",
    "success",
    "failed",
    "timeout",
    "busy",
})
TERMINAL_STATES = frozenset({"success", "failed", "timeout", "busy"})
WORKER_CODES = frozenset({
    "approval_pending",
    "otp_pending",
    "captcha_pending",
    "rejected",
    "attempts_exhausted",
    "not_implemented",
    "worker_error",
})

_EVENT_KEYS = frozenset({"version", "request_id", "challenge", "state", "code"})
_INTERACTIVE_STATES = frozenset({"approval_required", "otp_required", "captcha_required"})
_DEFAULT_WORKER = ("node", str(Path(__file__).resolve().parent / "headless" / "login-worker.js"))


class LoginProtocolError(ValueError):
    """The worker emitted data that does not satisfy the local protocol."""


@dataclass(frozen=True)
class LoginEvent:
    state: str
    code: str | None = None


@dataclass(frozen=True)
class LoginResult:
    state: str
    code: str | None = None


def _validate_identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise LoginProtocolError(f"invalid {name}")
    if any(character.isspace() for character in value):
        raise LoginProtocolError(f"invalid {name}")
    return value


def build_start_request(request_id: str, challenge: str) -> dict[str, str | int]:
    """Build the complete request schema; credentials are intentionally absent."""
    return {
        "version": PROTOCOL_VERSION,
        "action": "start",
        "request_id": _validate_identifier(request_id, "request_id"),
        "challenge": _validate_identifier(challenge, "challenge"),
    }


def parse_worker_event(
    line: str | bytes,
    *,
    expected_request_id: str,
    expected_challenge: str,
) -> LoginEvent:
    """Validate one bounded JSON-line event and bind it to this invocation."""
    raw = line.encode("utf-8") if isinstance(line, str) else line
    if not raw or len(raw) > MAX_MESSAGE_BYTES:
        raise LoginProtocolError("invalid worker message size")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LoginProtocolError("worker message is not valid JSON") from error
    if not isinstance(payload, dict) or not set(payload).issubset(_EVENT_KEYS):
        raise LoginProtocolError("worker message has unsupported fields")
    if set(payload) < {"version", "request_id", "challenge", "state"}:
        raise LoginProtocolError("worker message is incomplete")
    if payload["version"] != PROTOCOL_VERSION:
        raise LoginProtocolError("unsupported protocol version")

    request_id = _validate_identifier(payload["request_id"], "request_id")
    challenge = _validate_identifier(payload["challenge"], "challenge")
    if not hmac.compare_digest(request_id, expected_request_id):
        raise LoginProtocolError("worker request mismatch")
    if not hmac.compare_digest(challenge, expected_challenge):
        raise LoginProtocolError("worker challenge mismatch")

    state = payload["state"]
    if not isinstance(state, str) or state not in WORKER_STATES:
        raise LoginProtocolError("unsupported worker state")
    code = payload.get("code")
    if code is not None and (not isinstance(code, str) or code not in WORKER_CODES):
        raise LoginProtocolError("unsupported worker code")
    return LoginEvent(state, code)


class LoginProtocolSession:
    """Validate state ordering for one worker invocation."""

    def __init__(self, request_id: str, challenge: str):
        self.request_id = _validate_identifier(request_id, "request_id")
        self.challenge = _validate_identifier(challenge, "challenge")
        self.state: str | None = None

    def accept(self, payload: dict | str | bytes) -> LoginEvent:
        line = json.dumps(payload) if isinstance(payload, dict) else payload
        event = parse_worker_event(
            line,
            expected_request_id=self.request_id,
            expected_challenge=self.challenge,
        )
        if self.state in TERMINAL_STATES:
            raise LoginProtocolError("worker emitted an event after termination")
        if self.state is None:
            if event.state not in {"started", "busy"}:
                raise LoginProtocolError("worker did not start the protocol")
        elif self.state == "started" or self.state in _INTERACTIVE_STATES:
            allowed = _INTERACTIVE_STATES | {"success", "failed", "timeout"}
            if event.state not in allowed:
                raise LoginProtocolError("invalid worker state transition")
        self.state = event.state
        return event


async def verify_terminal_result(
    event: LoginEvent,
    verifier: Callable[[], bool | Awaitable[bool]],
) -> LoginResult:
    """Trust a success event only after Core independently verifies the session."""
    if event.state not in TERMINAL_STATES:
        raise LoginProtocolError("worker event is not terminal")
    if event.state != "success":
        return LoginResult(event.state, event.code)
    try:
        verified = verifier()
        if inspect.isawaitable(verified):
            verified = await verified
    except Exception:
        verified = False
    if verified is not True:
        return LoginResult("failed", "verification_failed")
    return LoginResult("success")


class LoginWorkerClient:
    """Launch one local worker without a shell and exchange bounded JSON lines."""

    def __init__(self, command: Sequence[str] = _DEFAULT_WORKER, timeout_seconds: float = 300.0):
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("worker command must be a non-empty argument sequence")
        if timeout_seconds <= 0:
            raise ValueError("worker timeout must be positive")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds
        self._lock = asyncio.Lock()

    async def run(
        self,
        verifier: Callable[[], bool | Awaitable[bool]],
        on_event: Callable[[LoginEvent], object] | None = None,
    ) -> LoginResult:
        if self._lock.locked():
            return LoginResult("busy")
        async with self._lock:
            return await self._run_locked(verifier, on_event)

    async def _run_locked(self, verifier, on_event) -> LoginResult:
        request_id = secrets.token_urlsafe(24)
        challenge = secrets.token_urlsafe(32)
        session = LoginProtocolSession(request_id, challenge)
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            request = json.dumps(build_start_request(request_id, challenge), separators=(",", ":"))
            process.stdin.write((request + "\n").encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()

            deadline = asyncio.get_running_loop().time() + self.timeout_seconds
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return LoginResult("timeout")
                line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
                if not line:
                    return LoginResult("failed", "worker_exit")
                event = session.accept(line)
                if on_event is not None:
                    callback_result = on_event(event)
                    if inspect.isawaitable(callback_result):
                        await callback_result
                if event.state in TERMINAL_STATES:
                    return await verify_terminal_result(event, verifier)
        except asyncio.TimeoutError:
            return LoginResult("timeout")
        except (LoginProtocolError, OSError, ValueError):
            return LoginResult("failed", "protocol_error")
        finally:
            if process is not None and process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
