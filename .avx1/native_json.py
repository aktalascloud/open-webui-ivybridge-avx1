"""Build orjson for Ivy Bridge with O3 and LTO or ThinLTO; no PGO."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import tarfile
import tomllib
import urllib.request

from common import ROOT, WORK, download, run, sha256, write_json

EXPERIMENTS = {
    'ivy-o3-fat-cgu1': {'lto':'fat','opt':3,'codegen':1},
    'ivy-o3-thin-cgu1': {'lto':'thin','opt':3,'codegen':1},
    'ivy-o3-thin-cgu8': {'lto':'thin','opt':3,'codegen':8},
    'ivy-o2-thin-cgu1': {'lto':'thin','opt':2,'codegen':1},
}

def build(destination, lto=None, experiment=None):
    profile=EXPERIMENTS[experiment] if experiment else None
    lto = profile['lto'] if profile else lto or os.environ.get("NATIVE_LTO", "fat")
    if lto not in ("fat", "thin"):
        raise ValueError("Expected fat or thin LTO")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["dependencies"]
    version = next(item.split("==")[1] for item in dependencies if item.startswith("orjson=="))
    with urllib.request.urlopen(f"https://pypi.org/pypi/orjson/{version}/json", timeout=60) as response:
        metadata = json.load(response)
    source = next(item for item in metadata["urls"] if item["packagetype"] == "sdist")
    archive = download(source["url"], WORK / "orjson.tar.gz", source["digests"]["sha256"])
    source_root = WORK / ("native-source-" + lto)
    source_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as stream:
        stream.extractall(source_root, filter="data")
    checkout = next(path for path in source_root.iterdir() if path.is_dir())
    run(sys.executable, "-m", "pip", "install", "maturin>=1.9,<2", "wheel")
    base_flags = "-C target-cpu=ivybridge -C target-feature=+sse4.2,+avx,+f16c,+popcnt,-avx2,-fma -C opt-level=3 -C embed-bitcode=yes"
    if profile:
        base_flags = ("-C target-cpu=ivybridge -C target-feature=+sse4.2,+avx,+f16c,+popcnt,-avx2,-fma "
                      f"-C opt-level={profile['opt']} -C embed-bitcode=yes")
    environment = dict(os.environ, CARGO_BUILD_JOBS="4", CARGO_INCREMENTAL="0", RUSTFLAGS=base_flags,
                       CARGO_PROFILE_RELEASE_LTO=lto, CARGO_TARGET_DIR=str(WORK / ("cargo-" + lto)))
    if profile:
        environment.update(CARGO_PROFILE_RELEASE_CODEGEN_UNITS=str(profile['codegen']),
                           CARGO_PROFILE_RELEASE_OPT_LEVEL=str(profile['opt']))
    environment.pop("LLVM_PROFILE_FILE", None)
    run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", destination,
        checkout, env=environment)
    wheel = next(Path(destination).glob("orjson*.whl"))
    result = {"package": "orjson", "version": version, "source_sha256": sha256(archive),
              "flags": base_flags, "pgo": False, "lto": lto, "wheel_sha256": sha256(wheel),
              "rustc": run("rustc", "--version", capture=True).stdout.strip()}
    if profile:result.update(experiment=experiment,codegen_units=profile['codegen'],opt_level=profile['opt'])
    write_json(destination / "native-build.json", result)
    (destination / "wheel.sha256").write_text(sha256(wheel) + "  " + wheel.name + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lto", choices=("fat", "thin"), default="fat")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.output, args.lto)
