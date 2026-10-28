"""
IP-address utilities: CIDR matching for trusted-proxy whitelists.

A `TRUSTED_PROXIES` env var is a comma-separated list of entries.
Each entry is one of:
  * A single IP literal (e.g. "127.0.0.1", "::1")
  * A CIDR block (e.g. "10.0.0.0/8", "fe80::/10")
  * A bare hostname (matched as `socket.gethostbyname`)

Entries are parsed lazily on first use; parse errors are logged and the
entry is skipped (fail-closed — better to reject a valid XFF than to
trust a malformed one).
"""
from __future__ import annotations

from . import managed_env


import ipaddress
import os
import socket
from typing import Iterable

from .logger import get_logger

log = get_logger("ip_utils")

_cached_entries: list | None = None


def _parse_entries(raw: str) -> list:
    """Return a list of `ipaddress.IPv4Network` / `IPv6Network` / single IP."""
    out: list = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            if "/" in chunk:
                out.append(ipaddress.ip_network(chunk, strict=False))
            else:
                out.append(ipaddress.ip_address(chunk))
        except ValueError:
            # Maybe a hostname? Resolve once.
            try:
                resolved = socket.gethostbyname(chunk)
                out.append(ipaddress.ip_address(resolved))
            except Exception as e:
                log.warning(
                    "trusted_proxy_parse_failed",
                    extra={"entry": chunk, "error": str(e)},
                )
    return out


def get_trusted_networks() -> list:
    """Lazily parse the TRUSTED_PROXIES env var (cached for the process lifetime)."""
    global _cached_entries
    if _cached_entries is None:
        raw = managed_env.get("TRUSTED_PROXIES", "").strip()
        _cached_entries = _parse_entries(raw)
    return _cached_entries


def is_trusted_proxy(ip: str | None) -> bool:
    """True if `ip` matches one of the configured trusted networks."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for net in get_trusted_networks():
        if isinstance(net, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
            if addr in net:
                return True
        else:
            if addr == net:
                return True
    return False


def get_real_client_ip(headers, peer_ip: str | None) -> str:
    """Pick the correct client IP, honouring X-Forwarded-For only when the
    peer (the immediate connection) is a trusted proxy.

    `headers` may be a dict-like or a FastAPI/Starlette Headers object.
    `peer_ip` is the IP the request actually came from (e.g. request.client.host).
    """
    if not is_trusted_proxy(peer_ip):
        return peer_ip or "unknown"
    fwd = headers.get("x-forwarded-for") if hasattr(headers, "get") else None
    if not fwd:
        fwd = headers.get("X-Forwarded-For") if hasattr(headers, "get") else None
    if fwd:
        first = fwd.split(",")[0].strip()
        if first:
            return first
    real = headers.get("x-real-ip") if hasattr(headers, "get") else None
    if not real:
        real = headers.get("X-Real-IP") if hasattr(headers, "get") else None
    if real:
        return real.strip()
    return peer_ip or "unknown"
