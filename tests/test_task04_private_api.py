import asyncio
from pathlib import Path

import httpx
import pytest

import main
from core_server import validate_bind_host


def test_internal_snapshot_requires_a_dedicated_token(monkeypatch):
    monkeypatch.setattr(main, "INTERNAL_API_TOKEN", "internal-test-token")
    monkeypatch.setattr(main, "SNAPSHOT_STORE", type("Store", (), {
        "load": lambda self: {"version": 1, "updated_at": "2026-01-01T00:00:00+00:00", "data": {"summary": {"total_balance": 12.5}}},
    })())

    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            denied = await client.get("/internal/v1/snapshot")
            allowed = await client.get("/internal/v1/snapshot", headers={"X-Internal-Token": "internal-test-token"})
        return denied, allowed

    denied, allowed = asyncio.run(exercise())

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["data"] == {"summary": {"total_balance": 12.5}}


def test_internal_snapshot_is_disabled_without_a_token(monkeypatch):
    monkeypatch.setattr(main, "INTERNAL_API_TOKEN", "")

    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/internal/v1/snapshot")

    assert asyncio.run(exercise()).status_code == 503


def test_cors_has_no_wildcards():
    cors = next(middleware for middleware in main.app.user_middleware if middleware.cls.__name__ == "CORSMiddleware")

    assert "*" not in cors.kwargs["allow_origins"]
    assert "*" not in cors.kwargs["allow_methods"]
    assert "*" not in cors.kwargs["allow_headers"]


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "100.64.0.10"])
def test_private_bind_accepts_loopback_or_tailscale_addresses(host):
    assert validate_bind_host(host) == host


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10"])
def test_private_bind_rejects_public_or_lan_addresses(host):
    with pytest.raises(ValueError):
        validate_bind_host(host)


def test_private_deployment_examples_do_not_publish_the_core():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    acl = Path("deploy/tailscale-acl.example.hujson").read_text(encoding="utf-8")
    service = Path("deploy/bitget-tracker-core.service.example").read_text(encoding="utf-8")

    assert "0.0.0.0" not in dockerfile
    assert 'CMD ["/app/docker-entrypoint.sh"]' in dockerfile
    entrypoint = Path("docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "run_core.py" in entrypoint
    assert "tag:bitget-viewer" in acl
    assert '"dst": ["tag:bitget-core"]' in acl
    assert '"ip": ["tcp:10000"]' in acl
    assert "EnvironmentFile=/etc/bitget-tracker/core.env" in service
    assert "Environment=SNAPSHOT_PATH=/var/lib/bitget-tracker/snapshot.json" in service
