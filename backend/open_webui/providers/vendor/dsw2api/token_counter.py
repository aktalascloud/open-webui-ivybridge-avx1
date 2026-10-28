"""
Token counting for usage statistics.

DeepSeek Chat does not expose token counts upstream, so we estimate
locally. We use ``tiktoken`` with the ``cl100k_base`` encoding — it
is the closest open-source tokenizer to DeepSeek's BPE (DeepSeek has
not published a tokenizer package). When ``tiktoken`` is not installed
or the model encoding cannot be resolved, we fall back to a deterministic
character-based heuristic so usage is never ``-1``.

The heuristic used as fallback:
  * 1 token ≈ 0.75 English word  →  ~1 token per 4 ASCII chars
  * 1 token ≈ 1 CJK character    →  ~1 token per CJK char
  * Mixed content is summed character-class-wise.

These numbers are conservative (they slightly over-count for English and
slightly under-count for CJK), which is the safer side to err on for
rate-limiting and billing use-cases.
"""
from __future__ import annotations

import os
import threading
from typing import Iterable

from .logger import get_logger

log = get_logger("token_counter")

# Lazy, process-global, thread-safe.
_lock = threading.Lock()
_encoder = None
_encoder_attempted = False


def _get_encoder():
    """Lazily load the tiktoken cl100k_base encoder.

    Returns None if tiktoken is not installed or the encoding cannot
    be downloaded. Callers must handle the None case.
    """
    global _encoder, _encoder_attempted
    if _encoder_attempted:
        return _encoder
    with _lock:
        if _encoder_attempted:
            return _encoder
        _encoder_attempted = True
        try:
            import tiktoken
            _encoder = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            log.warning("tiktoken_unavailable", extra={"error": str(e)})
            _encoder = None
    return _encoder


def _is_cjk(ch: str) -> bool:
    """True for CJK / full-width / kana codepoints (1 token per char)."""
    code = ord(ch)
    return (
        0x3000 <= code <= 0x303F        # CJK punctuation
        or 0x3400 <= code <= 0x4DBF     # CJK Ext A
        or 0x4E00 <= code <= 0x9FFF     # CJK Unified
        or 0xF900 <= code <= 0xFAFF     # CJK Compat
        or 0xFF00 <= code <= 0xFFEF     # Full-width
        or 0x3040 <= code <= 0x30FF     # Hiragana + Katakana
        or 0xAC00 <= code <= 0xD7AF     # Hangul syllables
    )


def _char_estimate(text: str) -> int:
    """Fallback heuristic: count tokens as roughly 1 per CJK char and
    1 per 4 ASCII chars, with 1 per ~2 for other Unicode.
    """
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        if ch.isspace():
            continue
        if _is_cjk(ch):
            cjk += 1
        else:
            other += 1
    # `other` covers ASCII, latin-extended, emoji, etc.
    return cjk + max(1, other // 4)


def count_text(text: str) -> int:
    """Return the estimated number of tokens for a single string."""
    if not text:
        return 0
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception as e:
            log.debug("tiktoken_encode_failed", extra={"error": str(e)})
    return _char_estimate(text)


def count_prompt(prompt: str | None) -> int:
    """Count tokens for an assembled prompt (text)."""
    return count_text(prompt or "")


def count_messages(messages: Iterable[dict]) -> int:
    """Sum token counts for an iterable of OpenAI/Anthropic-shaped message
    dicts. Each message contributes its text content + a small per-message
    overhead (4 tokens by convention; OpenAI reference is 4 per message).
    """
    total = 0
    for m in messages:
        total += 4  # per-message overhead
        content = m.get("content")
        if isinstance(content, str):
            total += count_text(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += count_text(str(block.get("text") or ""))
                else:
                    total += count_text(str(block))
        # tool_calls / tool_call_id content is intentionally not counted:
        # it would require re-running build_dsml_tool_prompt; the prompt
        # string already includes them, so callers should pass the prompt
        # to count_prompt() for the most accurate number.
    return total
