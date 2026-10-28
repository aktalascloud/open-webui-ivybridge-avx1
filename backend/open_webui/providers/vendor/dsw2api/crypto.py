"""
Fernet-based symmetric encryption for at-rest DeepSeek credentials.

The Fernet key is loaded from the `DEEPSEEK_ENCRYPTION_KEY` environment
variable. Generate one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Format on disk (data/accounts.json):
    {
      "version": 2,
      "encryption": "fernet",
      "accounts": [
        {
          "id": "...",
          "email": "...",
          "token": "gAAAAA...",          # Fernet ciphertext, OR plain if migrating
          "cookies": "gAAAAA...",
          "created_at": ...,
          "updated_at": ...
        }
      ]
    }

Migration: v1 stores (version=1, no `encryption` field) are read, the raw
token/cookies are encrypted in memory, and the file is rewritten as v2.
A `accounts.json.v1.bak` is left next to the file for rollback.
"""
from __future__ import annotations

from . import managed_env


import base64
import os
import shutil
from pathlib import Path
from typing import Any

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAVE_FERNET = True
except ImportError:  # pragma: no cover - tested in CI
    _HAVE_FERNET = False


STORE_VERSION_PLAIN = 1
STORE_VERSION_ENCRYPTED = 2


def _resolve_key() -> bytes | None:
    """Return the Fernet key, or None if not configured."""
    raw = managed_env.get("DEEPSEEK_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        # Accept both urlsafe base64 and plain bytes (some generators omit padding).
        if len(raw) % 4 != 0:
            raw += "=" * (4 - len(raw) % 4)
        key = base64.urlsafe_b64decode(raw.encode())
        if len(key) != 32:
            return None
        return raw.encode()
    except Exception:
        return None


def is_enabled() -> bool:
    """True when the user opted in to at-rest encryption AND cryptography is installed."""
    if not _HAVE_FERNET:
        return False
    return _resolve_key() is not None


def encrypt_str(plaintext: str) -> str:
    if not is_enabled():
        raise RuntimeError("DEEPSEEK_ENCRYPTION_KEY is not configured")
    return Fernet(_resolve_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_str(ciphertext: str) -> str:
    if not is_enabled():
        raise RuntimeError("DEEPSEEK_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(_resolve_key()).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise RuntimeError(
            "Failed to decrypt DeepSeek credentials. The DEEPSEEK_ENCRYPTION_KEY "
            "may have changed since the accounts file was last written."
        ) from e


# ── Store-level helpers (read / write accounts.json) ───────────────────────

def _is_ciphertext(value: str) -> bool:
    """Heuristic: Fernet ciphertext always starts with `gAAAAA` or `ZAAAAA`."""
    return isinstance(value, str) and (
        value.startswith("gAAAAA") or value.startswith("ZAAAAA")
    ) and len(value) > 50


def encrypt_account_dict(acct: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with token/cookies encrypted (in place of originals)."""
    if not is_enabled():
        return acct
    out = dict(acct)
    for field in ("token", "cookies"):
        v = out.get(field)
        if isinstance(v, str) and v and not _is_ciphertext(v):
            out[field] = encrypt_str(v)
    return out


def decrypt_account_dict(acct: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with token/cookies decrypted."""
    if not is_enabled():
        return acct
    out = dict(acct)
    for field in ("token", "cookies"):
        v = out.get(field)
        if isinstance(v, str) and v and _is_ciphertext(v):
            out[field] = decrypt_str(v)
    return out


def detect_store_version(payload: dict[str, Any]) -> int:
    """Return 1 for legacy plaintext, 2 for Fernet-encrypted, else 0."""
    if not isinstance(payload, dict):
        return 0
    if payload.get("encryption") == "fernet":
        return STORE_VERSION_ENCRYPTED
    return STORE_VERSION_PLAIN


def migrate_store_file(path: Path) -> dict[str, Any]:
    """Read accounts.json, transparently decrypting if needed, and return the
    in-memory dict. The on-disk representation is *not* rewritten here — the
    caller decides when to persist (so failed loads don't damage the file).
    """
    import json
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = detect_store_version(raw)
    if version == STORE_VERSION_PLAIN:
        if is_enabled():
            # Decrypt-on-the-fly: caller will rewrite the file in v2 form
            # on next save. We keep `raw` unchanged in storage layer.
            return raw
        return raw
    if version == STORE_VERSION_ENCRYPTED:
        if not is_enabled():
            raise RuntimeError(
                f"{path} is encrypted (v2) but DEEPSEEK_ENCRYPTION_KEY is unset. "
                "Set the key in .env or unset encryption by deleting the file."
            )
        for acct in raw.get("accounts", []):
            decrypted = decrypt_account_dict(acct)
            acct["token"] = decrypted["token"]
            acct["cookies"] = decrypted["cookies"]
        return raw
    raise RuntimeError(f"Unknown store version in {path}: {version}")


def maybe_upgrade_store_file(path: Path) -> None:
    """If the on-disk file is v1 and encryption is enabled, rewrite as v2.
    Leaves a `.v1.bak` alongside for rollback.
    """
    import json
    if not path.exists():
        return
    if not is_enabled():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if detect_store_version(payload) != STORE_VERSION_PLAIN:
        return
    bak = path.with_suffix(path.suffix + ".v1.bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    upgraded = {
        "version": STORE_VERSION_ENCRYPTED,
        "encryption": "fernet",
        "accounts": [encrypt_account_dict(a) for a in payload.get("accounts", [])],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(upgraded, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
