# Open WebUI · Ivy Bridge AVX1

[English](README.md) · [Русский](README.ru.md)

Experimental builds for personal compatibility and performance testing. Upstream application names and interface branding are retained.

[Upstream project](https://github.com/open-webui/open-webui) · [Packages](https://github.com/aktalascloud/open-webui-ivybridge-avx1/releases)

Download the single latest package, extract it and run `Install.cmd`. `Install.cmd -CheckOnly` verifies integrity without installing. Packages exclude personal configuration, credentials, history, caches and model weights. Models download from Hugging Face on demand.

One build combines current official source and reviewed fork patches. There are no separate stable/dev downloads.

## Patches

| ID | Change | Source |
|---|---|---|
| WEB-001 | Build the frontend from its lockfile with npm ci; remove forced dependency resolution. | `.avx1/PATCHES.json` |
| WEB-002 | Build orjson for Ivy Bridge with Rust O3 and LTO/ThinLTO, without PGO; compare on the actual CPU. | `.avx1/PATCHES.json` |
| WEB-003 | Source-level microphone provenance, bounded report speech, same-message speech identity and local call emoji; replaces chunk-name-dependent private overlays. | `.avx1/PATCHES.json` |
| WEB-004 | Patched browser dependency lock, current SheetJS tarball, sharp override and PDF.js 6; compatible Vite 7/Svelte plugin 6 toolchain. | `.avx1/PATCHES.json` |
| WEB-005 | Backport official Windows file URL normalization for encryption artifact verification without changing cryptographic code. | `.avx1/PATCHES.json` |
| WEB-006 | Upgrade twelve vulnerable runtime dependency pins; explicitly assess only four standalone Chroma HTTP-server advisories against the embedded/client boundary. New advisories remain blocking. | `.avx1/PATCHES.json` |
| WEB-007 | Preserve browser export conditions in Vite; verify the packaged login screen in Chromium. | `.avx1/PATCHES.json` |

## Measurements

Measured on 2026-10-23, Xeon E5-2697 v2, orjson 3.11.9, 23 compatibility vectors: stock 11152 ns, LTO 11362 ns (throughput -1.85%), ThinLTO 11848 ns (-5.88%). These are synthetic JSON results, not LLM speed. Stock remains the default. Use `Install.cmd -ExperimentalNativeJson` to try O3 LTO. PGO is disabled. [Method and raw results](.avx1/measurements/json-no-pgo-20261023.json).

The measured wheel (`e55bfb2846e5`) was measured on the actual Xeon: JSON throughput -2.63% versus stock; all 23 compatibility vectors matched. Stock remains the default. [Exact wheel result](.avx1/measurements/json-release-e55bfb2846e5.json).

## Licensing and compatibility

Original licenses, notices and license history are preserved. Each binary package includes its corresponding source. Private signing keys stay outside the repository. APKs use a separate application ID.

Local deployment additionally checks the owner's private filter and Telegram bridge. Their source, settings and data are not published. Unreviewed PR/fork changes remain candidates; accepted upstream fixes arrive through merges of official branches.
