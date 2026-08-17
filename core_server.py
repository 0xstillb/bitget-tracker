"""Private Core server launch helpers."""

import ipaddress
import os
from urllib.parse import urlsplit


def validate_bind_host(host: str) -> str:
    """Permit loopback, Tailscale, or private LAN addresses for the Core API.

    Private LAN ranges (RFC 1918) and 0.0.0.0 allow LAN access from the Pi
    Viewer or a home browser without an SSH tunnel; public addresses are
    always rejected so the Core is never exposed to the internet.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("CORE_BIND_HOST must be an IP address") from error
    if address.is_loopback:
        return str(address)
    if host == "0.0.0.0":
        return host
    tailscale = isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10")
    if tailscale:
        return str(address)
    private_lan = isinstance(address, ipaddress.IPv4Address) and any(
        address in ipaddress.ip_network(net) for net in (
            "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        )
    )
    if private_lan:
        return str(address)
    raise ValueError(
        "CORE_BIND_HOST must be loopback, Tailscale, or a private LAN address"
    )


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
        try:
            parsed.port
        except ValueError as error:
            raise ValueError(
                "CORE_CORS_ORIGINS must contain only explicit HTTP(S) origins"
            ) from error
        if (
            origin == "*"
            or any(character.isspace() for character in origin)
            or "\\" in origin
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.netloc.endswith(":")
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
