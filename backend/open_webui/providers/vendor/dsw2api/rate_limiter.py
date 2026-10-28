"""
In-process sliding-window rate limiter.

Used by ``server.py`` to throttle requests per API key and per client IP.
State is process-local; for multi-worker deployments (gunicorn -w N) the
effective limit is N * the configured RPM, since each worker has its own
counter.

Configuration (env vars):
  * ``ENABLE_RATE_LIMIT``   — "true" / "false" (default true)
  * ``CLIENT_RPM_PER_KEY``  — requests per minute per API key (default 60)
  * ``CLIENT_RPM_PER_IP``   — requests per minute per IP (default 120)

Limits of 0 disable the corresponding dimension.
"""
from __future__ import annotations

from . import managed_env


import os
import threading
import time
from collections import deque
from typing import Optional

from .logger import get_logger

log = get_logger("rate_limiter")


def _env_int(name: str, default: int) -> int:
    raw = managed_env.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = managed_env.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


class _Window:
    """Per-key sliding window of request timestamps."""

    __slots__ = ("_lock", "_ts", "_capacity", "_window_secs")

    def __init__(self, capacity: int, window_secs: int = 60):
        self._lock = threading.Lock()
        self._ts: deque[float] = deque()
        self._capacity = capacity
        self._window_secs = window_secs

    def check(self) -> tuple[bool, int, int, int]:
        """Return ``(allowed, remaining, limit, reset_secs)``.

        ``reset_secs`` is the wall-clock time until the oldest in-window
        request ages out (0 if no requests are in window).
        """
        if self._capacity <= 0:
            return True, -1, 0, 0
        now = time.time()
        cutoff = now - self._window_secs
        with self._lock:
            # Drop expired entries.
            while self._ts and self._ts[0] <= cutoff:
                self._ts.popleft()
            if len(self._ts) >= self._capacity:
                # Reset = time until the oldest in-window request expires.
                reset = max(0, int(self._ts[0] + self._window_secs - now))
                return False, 0, self._capacity, reset
            self._ts.append(now)
            remaining = max(0, self._capacity - len(self._ts))
            return True, remaining, self._capacity, 0


class RateLimiter:
    """Two-dimensional sliding window: per-key AND per-IP.

    A request is allowed only if BOTH dimensions permit it.
    """

    def __init__(self,
                 per_key: Optional[int] = None,
                 per_ip: Optional[int] = None,
                 enabled: Optional[bool] = None):
        self.enabled = _env_bool("ENABLE_RATE_LIMIT", True) if enabled is None else enabled
        self._per_key = per_key if per_key is not None else _env_int("CLIENT_RPM_PER_KEY", 60)
        self._per_ip = per_ip if per_ip is not None else _env_int("CLIENT_RPM_PER_IP", 120)
        self._key_windows: dict[str, _Window] = {}
        self._ip_windows: dict[str, _Window] = {}
        self._lock = threading.Lock()

    def _get_key_window(self, key: str) -> _Window:
        with self._lock:
            w = self._key_windows.get(key)
            if w is None:
                w = _Window(self._per_key)
                self._key_windows[key] = w
            return w

    def _get_ip_window(self, ip: str) -> _Window:
        with self._lock:
            w = self._ip_windows.get(ip)
            if w is None:
                w = _Window(self._per_ip)
                self._ip_windows[ip] = w
            return w

    def check(self, api_key: str | None, client_ip: str | None) -> tuple[bool, dict]:
        """Return ``(allowed, headers)``.

        ``headers`` always contains the three standard X-RateLimit-* fields.
        The per-IP and per-key dimensions use a different ``Limit`` value
        — the smaller of the two — to give the client a single number to
        reason about. Each dimension still enforces its own limit.
        """
        if not self.enabled:
            return True, {}

        headers: dict[str, str] = {}
        for label, key, getter in (
            ("key", api_key or "anon", self._get_key_window),
            ("ip", client_ip or "unknown", self._get_ip_window),
        ):
            w = getter(key)
            allowed, remaining, limit, reset = w.check()
            headers[f"X-RateLimit-Limit-{label}"] = str(limit) if limit > 0 else "unlimited"
            headers[f"X-RateLimit-Remaining-{label}"] = str(remaining) if remaining >= 0 else "unlimited"
            if reset:
                headers[f"X-RateLimit-Reset-{label}"] = str(reset)
            if not allowed:
                log.warning("rate_limit_exceeded", extra={"dimension": label, "id": key})
                # Surface the most-restrictive headers to the client.
                return False, {
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset),
                    "Retry-After": str(reset),
                }
        # Both dimensions passed — surface the tighter remaining count.
        return True, headers
