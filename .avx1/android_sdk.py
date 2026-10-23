"""Resolve stable Android SDK packages from Google's official repository metadata."""
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
import xml.etree.ElementTree as ET


def resolve_flutter():
    with urllib.request.urlopen("https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json", timeout=90) as response:
        data = json.load(response)
    release = next(item for item in data["releases"] if item["hash"] == data["current_release"]["stable"])
    return {"flutter_sha": release["hash"], "flutter_version": release["version"]}


def resolve():
    with urllib.request.urlopen("https://dl.google.com/android/repository/repository2-3.xml", timeout=90) as response:
        root = ET.fromstring(response.read())
    packages = [node for node in root if node.tag.endswith("remotePackage") and
                any(child.tag.endswith("channelRef") and child.attrib.get("ref") == "channel-0" for child in node)]
    def newest(prefix, pattern):
        candidates = [node.attrib["path"] for node in packages if node.attrib["path"].startswith(prefix)
                      and re.fullmatch(pattern, node.attrib["path"].split(";", 1)[1])]
        return max(candidates, key=lambda value: tuple(map(int, value.split(";", 1)[1].removeprefix("android-").split("."))))
    platform = newest("platforms;", r"android-\d+(?:\.\d+)?")
    version = platform.split("android-", 1)[1].split(".")
    return {"platform": platform, "api_level": int(version[0]), "minor_api_level": int(version[1]) if len(version) > 1 else 0,
            "build_tools": newest("build-tools;", r"\d+\.\d+\.\d+"),
            "commandline_tools": newest("cmdline-tools;", r"\d+\.\d+"),
            "ndk": "ndk;29.0.14206865", "metadata": "https://dl.google.com/android/repository/repository2-3.xml"}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    pins = json.loads((root / ".avx1/toolchains.json").read_text("utf-8"))["android"]
    sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ["ANDROID_HOME"])
    original = sdk / "cmdline-tools/latest/bin/sdkmanager"
    subprocess.run([str(original), pins["commandline_tools"]], check=True)
    manager = sdk / "cmdline-tools" / pins["commandline_tools"].split(";", 1)[1] / "bin/sdkmanager"
    subprocess.run([str(manager), "--licenses"], input="y\n" * 100, text=True, check=True)
    subprocess.run([str(manager), pins["platform"], pins["build_tools"], pins["ndk"]], check=True)
