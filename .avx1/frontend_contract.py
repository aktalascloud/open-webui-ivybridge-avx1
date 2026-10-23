"""Attest the reviewed source-level assistant hooks after a normal frontend build."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    contract = json.loads((ROOT / ".avx1/frontend-contract.json").read_text("utf-8"))
    for name, expected in contract["sources"].items():
        actual = hashlib.sha256((ROOT / name).read_text('utf-8').encode('utf-8')).hexdigest()
        if actual != expected:
            raise RuntimeError("Assistant source hook changed; review and tests required: " + name)
    assets = ROOT / "build"
    if not (assets / "index.html").is_file():
        raise RuntimeError("Frontend output missing")
    proof = {"schema": 1, "name": "owui-ivybridge-assistant-v1", "hooks": contract["hooks"],
             "helper_sha256": contract["helper_sha256"], "sources": contract["sources"],
             "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
             "assets": {path.relative_to(assets).as_posix(): digest(path) for path in sorted(assets.rglob("*"))
                        if path.is_file() and path.suffix in {".js", ".html"}}}
    (assets / "assistant-compatibility.json").write_text(json.dumps(proof, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
