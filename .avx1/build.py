"""Build one exact source revision. Outputs contain no local configuration."""
from __future__ import annotations
import base64
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import tomllib
import zipfile
import subprocess

from common import ROOT, WORK, OUT, SecretPatternError, download, run, sha256, verify_archive, write_json, zip_folder


def license_files(destination):
    destination.mkdir(parents=True, exist_ok=True)
    paths = [path for path in ROOT.iterdir() if path.is_file() and
             any(word in path.name.upper() for word in ("LICENSE", "NOTICE", "COPYING", "CONTRIBUTOR_LICENSE"))]
    if not any(path.name.upper().startswith(("LICENSE", "COPYING")) for path in paths):
        raise RuntimeError("Project license missing")
    for path in paths:
        shutil.copy2(path, destination / path.name)


def audit_python(wheels, manifest):
    target = WORK / "audit-packages"
    run(sys.executable, "-m", "pip", "install", "--no-cache-dir", "--target", target, *wheels)
    run(sys.executable, "-m", "pip", "install", "pip-audit")
    report = WORK / "pip-audit.json"
    # A missing advisory service or unresolved advisory blocks publication.
    audit=subprocess.run([sys.executable,'-m','pip_audit','--path',str(target),'--strict','--format','json','--output',str(report)],cwd=ROOT)
    if audit.returncode not in {0,1} or not report.exists():raise RuntimeError('Dependency audit unavailable; publication blocked')
    data = json.loads(report.read_text("utf-8"))
    from security_scope import review
    assessment=review(data,ROOT)
    write_json(WORK/'security-review.json',assessment)
    manifest["security"] = {"python_audit": "passed with explicit applicability review", "dependencies": len(data["dependencies"]),
                            'assessment':assessment}
    manifest["resolved_dependencies"] = [{"name": item["name"], "version": item["version"]} for item in data["dependencies"]]
    return target


def build_python(project, package, manifest):
    wheels = package / "wheels"
    wheels.mkdir()
    environment = dict(os.environ, CYPRESS_INSTALL_BINARY="0", HUSKY="0", PIP_DISABLE_PIP_VERSION_CHECK="1")
    run(sys.executable, "-m", "pip", "install", "build", "hatchling", "wheel")
    if project == "webui":
        run("node", "--test", ROOT / ".avx1/frontend_contract.test.mjs", env=environment)
        # The reviewed hatch hook uses npm ci and the checked-in lockfile.
        run(sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", wheels, env=environment)
        run("npm", "audit", "--omit=dev", "--audit-level=high", env=environment)
        from native_json import build
        manifest["native_json"] = build(wheels)
        policy = json.loads((ROOT / ".avx1/native-policy.json").read_text("utf-8"))
        if policy["default"] not in ("stock", "optimized"):
            raise RuntimeError("Unknown native JSON selection policy")
        manifest["native_json"].update(policy)
    else:
        run(sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", wheels, env=environment)
    wheel_paths = list(wheels.glob("*.whl"))
    for path in wheel_paths:
        verify_archive(path)
    audit_target = audit_python(wheel_paths, manifest)
    def checked_script(script, *arguments):
        # --target installs do not process .pth files through PYTHONPATH alone.
        # pywin32 uses one to register its win32 paths and DLL directory.
        launcher = "import runpy,site,sys;site.addsitedir(sys.argv[1]);sys.argv=sys.argv[2:];runpy.run_path(sys.argv[0],run_name='__main__')"
        run(sys.executable, "-c", launcher, audit_target, script, *arguments)
    if project == "terminal":
        checked_script(ROOT / ".avx1/test_terminal.py")
    else:
        checked_script(ROOT / ".avx1/test_mcp_compat.py", "--source", ROOT / "backend/open_webui")
        checked_script(ROOT / ".avx1/bench_json.py")
        checked_script(ROOT / ".avx1/test_frontend_browser.py")
        manifest['security']['browser_smoke']='Chromium rendered the packaged login form without JavaScript page errors'
    bootstrap = package / "bootstrap"
    bootstrap.mkdir()
    run(sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:", "pip", "--dest", bootstrap)
    manifest["python"] = json.loads((ROOT / ".avx1/toolchains.json").read_text("utf-8"))["python"]
    manifest["optimization_scope"] = (
        "orjson experiment: Rust O3 + LTO for Ivy Bridge, no PGO; stock wheel is the measured faster default; Python/TypeScript retain normal semantics"
        if project == "webui" else "Pure Python application; native compiler flags do not optimize Python bytecode"
    )


def build_desktop(package, manifest):
    environment = dict(os.environ, npm_config_build_from_source="true", CSC_IDENTITY_AUTO_DISCOVERY="false")
    # MSVC O2 is its highest standard optimization level; /fp:precise preserves numerical semantics.
    environment["CL"] = "/O2 /Ob3 /GL /arch:AVX /fp:precise"
    environment["_LINK_"] = "/LTCG"
    run("npm", "ci", "--no-audit", "--no-fund", env=environment)
    run("npm", "audit", "--omit=dev", "--audit-level=high", env=environment)
    run("npm", "run", "build", env=environment)
    run("npx", "--no-install", "electron-builder", "--win", "--x64", "--dir", "--publish", "never",
        "-c.win.signAndEditExecutable=false", env=environment)
    shutil.copytree(ROOT / "dist/win-unpacked", package / "desktop", ignore=shutil.ignore_patterns("*.pdb", "*.map"))
    manifest["security"] = {"npm_runtime_audit": "passed; high/critical gate"}
    manifest["optimization_scope"] = "node-pty rebuilt with MSVC O2/GL/LTCG/AVX; Electron/Chromium use upstream prebuilt engines"
    manifest["authenticode"] = "Unsigned community build"


def build_conduit(package, manifest, channel):
    toolchains = json.loads((ROOT / ".avx1/toolchains.json").read_text("utf-8"))
    flutter_root = WORK / "flutter"
    run("git", "init", flutter_root)
    run("git", "-C", flutter_root, "remote", "add", "origin", "https://github.com/flutter/flutter.git")
    run("git", "-C", flutter_root, "fetch", "--depth=1", "origin", toolchains["flutter_sha"])
    run("git", "-C", flutter_root, "checkout", "--detach", "FETCH_HEAD")
    run("git", "-C", flutter_root, "fetch", "--depth=1", "origin",
        f"refs/tags/{toolchains['flutter_version']}:refs/tags/{toolchains['flutter_version']}")
    if run("git", "-C", flutter_root, "rev-parse", f"{toolchains['flutter_version']}^{{commit}}", capture=True).stdout.strip() != toolchains["flutter_sha"]:
        raise RuntimeError("Flutter tag/hash mismatch")
    run("git", "-C", flutter_root, "switch", "--create", "stable")
    flutter = flutter_root / "bin/flutter"
    dart = flutter_root / "bin/dart"
    os.environ["PATH"] = str(flutter_root / 'bin') + os.pathsep + os.environ['PATH']
    run(flutter, "--version")
    run("git", "submodule", "update", "--init", "--recursive", "--depth", "1", "third_party/katex", "third_party/mermaid")
    run(flutter, "pub", "get", "--enforce-lockfile")
    # Workspace members must finish their code generation before the app.
    for parent in (ROOT / "packages", ROOT / "apps"):
        if parent.exists():
            for folder in sorted(parent.iterdir()):
                pubspec = folder / "pubspec.yaml"
                if pubspec.exists() and re.search(r"(?m)^  build_runner:", pubspec.read_text("utf-8")):
                    run(dart, "run", "build_runner", "build", "--delete-conflicting-outputs", cwd=folder)
    run(dart, "run", "build_runner", "build", "--delete-conflicting-outputs")
    run(flutter, "analyze", "--no-fatal-infos", "--no-fatal-warnings")
    run(flutter, "test")
    outdated = run(flutter, "pub", "outdated", "--json", capture=True).stdout
    (WORK / "dependency-review.json").write_text(outdated, encoding="utf-8")
    key = WORK / "conduit-signing.p12"
    properties = ROOT / "android/key.properties"
    password = os.environ["CONDUIT_KEYSTORE_PASSWORD"]
    key.write_bytes(base64.b64decode(os.environ["CONDUIT_KEYSTORE_BASE64"], validate=True))
    properties.write_text(f"storeFile={key.as_posix()}\nstorePassword={password}\nkeyPassword={password}\nkeyAlias=conduit\n", encoding="utf-8")
    android = toolchains["android"]
    environment = dict(os.environ, ORG_GRADLE_PROJECT_avx1Channel=channel,
                       ORG_GRADLE_PROJECT_avx1ApiLevel=str(android["api_level"]),
                       ORG_GRADLE_PROJECT_avx1MinorApiLevel=str(android["minor_api_level"]))
    manifest["android_sdk"] = android
    try:
        symbols = WORK / "private-symbols"
        run(flutter, "build", "apk", "--release", "--split-per-abi", "--target-platform", "android-arm64",
            "--tree-shake-icons", "--obfuscate", f"--split-debug-info={symbols}",
            f"--build-number={int(time.time())}", env=environment)
    finally:
        properties.unlink(missing_ok=True)
        key.unlink(missing_ok=True)
    apk = ROOT / "build/app/outputs/flutter-apk/app-arm64-v8a-release.apk"
    if not apk.is_file():
        raise RuntimeError("ARM64 APK missing")
    sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ["ANDROID_HOME"])
    apksigner = sorted((sdk / "build-tools").glob("*/apksigner"))[-1]
    signing = run(apksigner, "verify", "--verbose", "--print-certs", apk, capture=True).stdout
    manifest["apk_signing"] = signing.strip().splitlines()
    with zipfile.ZipFile(apk) as archive:
        abis = {item.split("/")[1] for item in archive.namelist() if item.startswith("lib/")}
        if abis != {"arm64-v8a"}:
            raise RuntimeError(f"Unexpected APK architectures: {abis}")
    shutil.copy2(apk, package / f"conduit-{channel}-arm64-v8a.apk")
    manifest["optimization_scope"] = "Flutter release AOT, ARM64 only, icon tree shaking, R8 minification/resource shrinking, Dart obfuscation"
    manifest["security"] = {"flutter_tests": "passed", "apk_signature": "verified",
                            "dependency_review": "outdated report; not a complete vulnerability audit"}
    manifest["application_id"] = "io.github.aktalascloud.conduit" + (".dev" if channel == "development" else "")
    manifest["device_performance"] = "Not measured on a physical Android device"


def main():
    project = json.loads((ROOT / ".avx1/project.json").read_text("utf-8"))
    channel = os.environ.get("BUILD_CHANNEL", "development")
    day = os.environ.get("BUILD_DAY") or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    if channel not in {"stable", "development"} or not re.fullmatch(r"\d{8}", day):
        raise ValueError("Invalid build channel/date")
    if WORK.exists() or OUT.exists():
        raise RuntimeError("Use a fresh checkout for each build")
    WORK.mkdir()
    OUT.mkdir()
    run(sys.executable, ROOT / '.avx1/test_public_gate.py')
    run(sys.executable, ROOT / '.avx1/test_security_scope.py')
    package = WORK / "package"
    package.mkdir()
    manifest = {"schema": 1, "project": project["id"], "upstream": project["upstream"],
                "repository": project["repository"], "channel": channel, "day": day,
                "source_commit": run("git", "rev-parse", "HEAD", capture=True).stdout.strip(),
                "upstream_commit": project["upstream_commit"], "stable_tag": project["stable_tag"],
                "built_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "llm_weights_included": False,
                "llm_speedup_percent": None}
    license_files(package / "licenses")
    for name in ("Install.cmd", "Install.ps1", "bench_json.py"):
        shutil.copy2(ROOT / ".avx1" / name, package / name)
    if project["id"] in {"webui", "terminal"}:
        build_python(project["id"], package, manifest)
    elif project["id"] == "desktop":
        build_desktop(package, manifest)
    else:
        build_conduit(package, manifest, channel)
    shutil.copy2(ROOT / ".avx1/PATCHES.json", package / "PATCHES.json")
    # Exact corresponding source accompanies every binary; all upstream notices remain in it.
    source = package / "corresponding-source.tar.gz"
    run("git", "archive", "--format=tar.gz", "--output", source, "HEAD")
    manifest["files"] = [{"path": path.relative_to(package).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}
                         for path in sorted(package.rglob("*")) if path.is_file()]
    write_json(package / "manifest.json", manifest)
    name = f"{project['slug']}-{channel}-{day}-{manifest['source_commit'][:8]}.zip"
    archive = OUT / name
    zip_folder(package, archive)
    write_json(OUT / f"{name}.manifest.json", {**manifest, "archive": name, "archive_sha256": sha256(archive)})
    (OUT / f"{name}.sha256").write_text(f"{sha256(archive)}  {name}\n", encoding="ascii")
    print(f"Candidate verified: {name}")


if __name__ == "__main__":
    try:
        main()
    except SecretPatternError as error:
        write_json(WORK/'security-gate.json',error.metadata)
        raise
