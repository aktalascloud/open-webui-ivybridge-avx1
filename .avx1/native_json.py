"""Build orjson for Ivy Bridge with Rust O3, fat LTO and measured PGO."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tomllib
import urllib.request

from common import ROOT, WORK, download, run, sha256, write_json


def build(destination):
    dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["dependencies"]
    version = next(item.split("==")[1] for item in dependencies if item.startswith("orjson=="))
    with urllib.request.urlopen(f"https://pypi.org/pypi/orjson/{version}/json", timeout=60) as response:
        metadata = json.load(response)
    source = next(item for item in metadata["urls"] if item["packagetype"] == "sdist")
    archive = download(source["url"], WORK / "orjson.tar.gz", source["digests"]["sha256"])
    source_root = WORK / "native-source"
    source_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as stream:
        stream.extractall(source_root, filter="data")
    checkout = next(path for path in source_root.iterdir() if path.is_dir())
    run(sys.executable, "-m", "pip", "install", "maturin>=1.9,<2", "wheel")
    run("rustup", "component", "add", "llvm-tools-preview")
    sysroot = Path(run("rustc", "--print", "sysroot", capture=True).stdout.strip())
    profdata = next(sysroot.glob("lib/rustlib/*/bin/llvm-profdata.exe"))
    profiles = WORK / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    base_flags = "-C target-cpu=ivybridge -C target-feature=-avx2,-fma -C opt-level=3 -C embed-bitcode=yes -C lto=fat"
    environment = dict(os.environ, CARGO_BUILD_JOBS="4", CARGO_INCREMENTAL="0")
    environment.update(RUSTFLAGS=f"{base_flags} -C profile-generate={profiles.as_posix()}",
                       CARGO_TARGET_DIR=str(WORK / "cargo-instrument"),
                       LLVM_PROFILE_FILE=str(profiles / "%p-%m.profraw"))
    training = WORK / "training-wheels"
    training.mkdir(exist_ok=True)
    run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", training,
        checkout, env=environment)
    train_env = WORK / "training-env"
    run(sys.executable, "-m", "venv", train_env)
    train_python = train_env / "Scripts/python.exe"
    run(train_python, "-m", "pip", "install", "--no-deps", next(training.glob("*.whl")))
    run(train_python, ROOT / ".avx1/bench_json.py", "--train", env=environment)
    raw = list(profiles.glob("*.profraw"))
    if not raw:
        raise RuntimeError("PGO training did not produce profiles")
    merged = WORK / "orjson.profdata"
    run(profdata, "merge", "-o", merged, *raw)
    environment.update(RUSTFLAGS=f"{base_flags} -C profile-use={merged.as_posix()} -C llvm-args=-pgo-warn-missing-function",
                       CARGO_TARGET_DIR=str(WORK / "cargo-optimized"))
    environment.pop("LLVM_PROFILE_FILE", None)
    run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", destination,
        checkout, env=environment)
    wheel = next(Path(destination).glob("orjson*.whl"))
    return {"package": "orjson", "version": version, "source_sha256": sha256(archive),
            "flags": base_flags, "pgo": "trained; profile-use", "wheel_sha256": sha256(wheel),
            "llvm_profdata": run(profdata, "--version", capture=True).stdout.strip()}
