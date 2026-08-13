"""Private Core server launch helpers."""

import ipaddress
import os
from urllib.parse import urlsplit


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


def parse_cors_origins(raw: str) -> tuple[str, ...]:
    """Accept only explicit HTTP(S) origins without credentials or URL paths."""
    origins: list[str] = []
    for candidate in raw.split(","):
        origin = candidate.strip().rstrip("/")
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (
            origin == "*"
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("CORE_CORS_ORIGINS must contain only explicit HTTP(S) origins")
        origins.append(origin)
    if not origins:
        raise ValueError("CORE_CORS_ORIGINS must contain at least one explicit origin")
    return tuple(dict.fromkeys(origins))
