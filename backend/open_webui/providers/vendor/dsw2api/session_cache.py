"""
Multi-turn conversation cache.

DeepSeek Chat's API accepts a ``parent_message_id`` to thread replies
inside a ``chat_session_id``. To support multi-turn conversations on the
OpenAI / Anthropic compatible endpoints, we cache a small per-conversation
record and reuse it when a client sends a stable identity token.

Cache key: a server-generated value scoped to the authenticated caller (or
client IP when unauthenticated) and an explicit conversation identifier.

``conversation_id`` resolution order (highest first):
  1. The OpenAI request's top-level ``user`` field (string).
  2. The Anthropic request's ``metadata.user_id`` field.
  3. No cache entry.  Reusing an upstream session without an explicit
     conversation id can join independent conversations that happen to have
     the same opening message.

Cache value: ``ChatSession(chat_session_id, account_id, parent_message_id,
msg_counters)``.  The account binding prevents a session created with one
DeepSeek account from ever being submitted with another account's credentials.

TTL: configured via ``SESSION_CACHE_TTL`` (default 1800 seconds). Expired
entries are evicted on read; an opportunistic full sweep runs at most
once every ``SWEEP_INTERVAL`` seconds.
"""
from __future__ import annotations

from . import managed_env


import hashlib
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from .logger import get_logger

log = get_logger("session_cache")


def _env_int(name: str, default: int) -> int:
    raw = managed_env.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


SESSION_CACHE_TTL = _env_int("SESSION_CACHE_TTL", 1800)
SESSION_CACHE_MAX = _env_int("SESSION_CACHE_MAX", 10_000)
SWEEP_INTERVAL = 60  # seconds


def delta_prompt(prev: str, cur: str) -> str | None:
    """Compute the incremental prompt tail for a reused chat session.

    Agents (opencode, Claude Code, ...) always resend the full message
    history on every turn. If the proxy re-sends that whole history as the
    upstream ``prompt`` on a reused session, the DeepSeek conversation
    embeds every previous turn again per message (quadratic growth) —
    which looks like bot spam and can trigger account mutes.

    Returns:
      * the new tail only when ``cur`` extends ``prev`` ("User: <new>" only)
      * ``cur`` itself when it is an exact replay of the same turn
        (client retry — the upstream should answer again)
      * ``None`` when the histories diverge — the caller should abandon
        the cached session and start a fresh chain (a partial or edited
        history can't be expressed as a continuation)
    """
    if not isinstance(prev, str) or not isinstance(cur, str):
        return cur
    if cur == prev:
        return cur
    if cur.startswith(prev):
        tail = cur[len(prev):].lstrip("\n ")
        return tail if tail else cur
    return None


@dataclass
class ChatSession:
    chat_session_id: str
    # Upstream session IDs are account-owned.  An empty value represents a
    # legacy/incomplete in-memory entry and is deliberately never reusable.
    account_id: str = ""
    parent_message_id: int = 0
    msg_counters: dict[str, int] | None = None
    # The exact full prompt text that was sent for the last turn of this
    # session. Used to compute incremental (delta) prompts on the next turn
    # so the upstream conversation doesn't embed repeated history.
    sent_prompt: str = ""
    # Turns whose history did not extend ``sent_prompt`` (the client sent only
    # the newest message, or edited/truncated the history). Those turns resend
    # the full prompt on the existing chain instead of abandoning the session;
    # this counter is telemetry for that path.
    diverged_turns: int = 0
    # File references only: bounded, caller-scoped and bound to account_id.
    image_files: dict[str, str] = field(default_factory=dict)
    credential_fingerprint: str = ''

    def next_message_id(self) -> int:
        """Return the next ``parent_message_id`` and bump the counter."""
        if self.msg_counters is None:
            self.msg_counters = {}
        # Use the chat_session_id as the counter key. The upstream PoW header
        # is per-session, so a single session_id is the right granularity.
        cur = self.msg_counters.get(self.chat_session_id, self.parent_message_id)
        cur += 1
        self.msg_counters[self.chat_session_id] = cur
        self.parent_message_id = cur
        return cur


class SessionCache:
    """Thread-safe LRU+TTL cache of ChatSession objects keyed by conversation."""

    def __init__(self, ttl: int | None = None, max_size: int | None = None):
        self._ttl = ttl if ttl is not None else SESSION_CACHE_TTL
        self._max_size = max_size if max_size is not None else SESSION_CACHE_MAX
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple[float, ChatSession]] = OrderedDict()
        self._last_sweep = 0.0

    @staticmethod
    def derive_conversation_id(user_id: str | None, metadata: dict | None) -> str | None:
        """Return an explicit stable conversation identifier, if supplied.

        Never infer identity from message content: the same first prompt is a
        common occurrence and must not cause two callers to share upstream
        context.
        """
        if isinstance(user_id, str) and user_id.strip():
            return f"user:{user_id.strip()}"
        if metadata and isinstance(metadata, dict):
            uid = metadata.get("user_id")
            if isinstance(uid, str) and uid.strip():
                return f"user:{uid.strip()}"
        return None

    @staticmethod
    def derive_cache_key(scope: str, conversation_id: str | None) -> str | None:
        """Create an opaque cache key without retaining caller identifiers."""
        if not scope or not conversation_id:
            return None
        material = f"{scope}\0{conversation_id}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def get(self, key: str) -> Optional[ChatSession]:
        if not self._ttl or not key:
            return None
        now = time.time()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at, sess = entry
            if expires_at <= now:
                del self._data[key]
                return None
            # LRU: move to end
            self._data.move_to_end(key)
            return sess

    def put(self, key: str, session: ChatSession) -> None:
        if not self._ttl or not key:
            return
        expires_at = time.time() + self._ttl
        with self._lock:
            self._data[key] = (expires_at, session)
            self._data.move_to_end(key)
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)
        self._maybe_sweep()

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def _maybe_sweep(self) -> None:
        now = time.time()
        if now - self._last_sweep < SWEEP_INTERVAL:
            return
        self._last_sweep = now
        with self._lock:
            expired = [k for k, (exp, _) in self._data.items() if exp <= now]
            for k in expired:
                del self._data[k]
        if expired:
            log.debug("session_cache_swept", extra={"evicted": len(expired)})

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._data),
                "max_size": self._max_size,
                "ttl_secs": self._ttl,
            }
