from pathlib import Path


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def test_core_systemd_orders_after_tailscale_and_has_operational_limits():
    unit = _read("deploy/bitget-tracker-core.service.example")

    assert "After=network-online.target tailscaled.service" in unit
    assert "Wants=network-online.target tailscaled.service" in unit
    assert "Restart=on-failure" in unit
    assert "RestartSec=5" in unit
    assert "UMask=0077" in unit
    assert "StandardOutput=journal" in unit
    assert "StandardError=journal" in unit
    assert "LogRateLimitIntervalSec=30s" in unit
    assert "LogRateLimitBurst=200" in unit
    assert "MemoryMax=1G" in unit
    assert "CPUQuota=200%" in unit
    assert "TasksMax=512" in unit
    assert "ReadWritePaths=/var/lib/bitget-tracker" in unit


def test_pi_systemd_is_isolated_bounded_and_tailscale_ordered():
    unit = _read("deploy/bitget-pi-viewer.service.example")

    assert "After=network-online.target tailscaled.service" in unit
    assert "Wants=network-online.target tailscaled.service" in unit
    assert "Restart=on-failure" in unit
    assert "UMask=0077" in unit
    assert "StandardOutput=journal" in unit
    assert "LogRateLimitIntervalSec=30s" in unit
    assert "MemoryMax=128M" in unit
    assert "CPUQuota=50%" in unit
    assert "TasksMax=64" in unit
    assert "ReadWritePaths=/var/lib/bitget-pi-viewer" in unit
    assert "User=bitget-viewer" in unit


def test_tmpfiles_examples_create_private_persistent_directories():
    core = _read("deploy/bitget-tracker-core.tmpfiles.example.conf")
    viewer = _read("deploy/bitget-pi-viewer.tmpfiles.example.conf")

    assert "d /var/lib/bitget-tracker 0700 bitget bitget" in core
    assert "d /var/lib/bitget-pi-viewer 0700 bitget-viewer bitget-viewer" in viewer


def test_vps_compose_example_is_private_persistent_and_resource_bounded():
    compose = _read("deploy/compose.vps.example.yml")

    assert "network_mode: host" in compose
    assert "ports:" not in compose
    assert "/etc/bitget-tracker/core.env" in compose
    assert "/var/lib/bitget-tracker:/var/lib/bitget-tracker" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "mem_limit: 1g" in compose
    assert 'cpus: "2.0"' in compose
    assert "pids_limit: 512" in compose
    assert "max-size: 10m" in compose
    assert "max-file: \"3\"" in compose
    assert "restart: on-failure:5" in compose


def test_deployment_runbook_documents_preflight_coexistence_and_rollback():
    runbook = _read("deploy/DEPLOYMENT.md")
    lowered = runbook.lower()

    assert "grimmory" in lowered
    assert "moode" in lowered
    assert "do not stop, disable, restart, or modify" in lowered
    assert "ss -ltnp" in lowered
    assert "tailscale" in lowered
    assert "/var/lib/bitget-tracker" in runbook
    assert "/var/lib/bitget-pi-viewer" in runbook
    assert "journalctl" in lowered
    assert "rollback" in lowered
    assert "previous release" in lowered
    assert "never roll back or delete persistent state automatically" in lowered
    assert "manual validation" in lowered
