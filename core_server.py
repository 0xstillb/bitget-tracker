"""Private Core server launch helpers."""

import ipaddress
import os


def validate_bind_host(host: str) -> str:
    """Permit only loopback or a Tailscale CGNAT address for the Core API."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("CORE_BIND_HOST must be an IP address") from error
    tailscale = isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10")
    if not (address.is_loopback or tailscale):
        raise ValueError("CORE_BIND_HOST must be loopback or a Tailscale 100.64.0.0/10 address")
    return str(address)


def bind_host_from_env() -> str:
    return validate_bind_host(os.environ.get("CORE_BIND_HOST", "127.0.0.1"))
