"""Small, dependency-free helpers shared by the public build recipes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".avx1-work"
OUT = ROOT / ".avx1-out"


def run(*args, cwd=ROOT, env=None, capture=False):
    command = [str(arg) for arg in args]
    command[0] = shutil.which(command[0]) or command[0]
    return subprocess.run(command, cwd=cwd, env=env, check=True,
                          text=True, encoding="utf-8", errors="replace",
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, path, expected=None):
    if not url.startswith("https://"):
        raise ValueError("HTTPS required")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, path.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    if expected and sha256(path) != expected:
        path.unlink()
        raise ValueError("Download checksum mismatch")
    return path


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


SECRET_PATTERNS = [
    rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
    rb"gh[pousr]_[A-Za-z0-9]{30,}",
    rb"github_pat_[A-Za-z0-9_]{40,}",
    rb"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}",
    rb"[0-9]{8,12}:[A-Za-z0-9_-]{30,}",
]
FORBIDDEN_PARTS = {".git", "__pycache__", ".venv", "node_modules", "logs", "cache", "uploads"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pdb", ".jks", ".p12", ".pem", ".key", ".gguf", ".safetensors"}


def scan_bytes(data, label):
    for content in (data, data.replace(b"\x00", b"")):
        if any(re.search(pattern, content) for pattern in SECRET_PATTERNS):
            raise ValueError(f"Secret pattern in {label}; contents withheld")


def verify_archive(path):
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"Archive CRC failure: {bad}")
        for entry in archive.infolist():
            parts = Path(entry.filename.replace("\\", "/")).parts
            if entry.filename.startswith(("/", "\\")) or ".." in parts:
                raise ValueError("Unsafe archive member")
            forbidden = set(parts) & FORBIDDEN_PARTS
            if entry.filename.startswith("desktop/resources/app.asar.unpacked/node_modules/"):
                forbidden.discard("node_modules")
            if forbidden or Path(entry.filename).suffix.lower() in FORBIDDEN_SUFFIXES:
                raise ValueError(f"Private/runtime residue: {entry.filename}")
            if not entry.is_dir():
                scan_bytes(archive.read(entry), entry.filename)


def zip_folder(folder, target):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(Path(folder).rglob("*")):
            if path.is_symlink():
                raise ValueError("Symlink in package")
            if path.is_file():
                scan_bytes(path.read_bytes(), path.name)
                archive.write(path, path.relative_to(folder).as_posix())
    verify_archive(target)
