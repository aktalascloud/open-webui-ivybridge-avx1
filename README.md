# Open WebUI · Ivy Bridge AVX1

[English](README.md) · [Русский](README.ru.md)

Experimental builds for personal compatibility and performance testing. Upstream application names and interface branding are retained.

[Upstream project](https://github.com/open-webui/open-webui) · [Packages](https://github.com/aktalascloud/open-webui-ivybridge-avx1/releases)

Extract the appropriate archive and run `Install.cmd`. `Install.cmd -CheckOnly` verifies integrity without installing. Packages exclude personal configuration, credentials, history, caches and model weights. Models download from Hugging Face on demand.

## Patches

| ID | Change | Source |
|---|---|---|
| WEB-001 | Build the frontend from its lockfile with npm ci; remove forced dependency resolution. | local |
| WEB-002 | Build orjson for Ivy Bridge with Rust O3, LTO/ThinLTO without PGO; qualify on the target CPU. | local recipe |
| WEB-003–005 | Source-level assistant voice/microphone compatibility; patched browser dependencies; official Windows build fix. | See `.avx1/PATCHES.json` |

## Measurements

| Metric | Verified improvement |
|---|---|
| LLM generation throughput | Not measured |
| JSON on Ivy Bridge | Pending stock/optimized comparison |
| Android runtime performance | Not measured on a physical phone |

Unmeasured changes have no claimed percentage. JSON timings cover serialization/parsing, not tokens/s. LTO and ISA flags apply only to the named native components; they do not turn Python or TypeScript into native code. AVX2/FMA and fast-math are not enabled.

## Licensing and compatibility

Original licenses, notices and license history are preserved. Each binary package includes its corresponding source. Private signing keys stay outside the repository. APKs use a separate application ID.

Local deployment additionally checks the owner's private filter and Telegram bridge. Their source, settings and data are not published. Unreviewed PR/fork changes remain candidates; accepted upstream fixes arrive through merges of official branches.
