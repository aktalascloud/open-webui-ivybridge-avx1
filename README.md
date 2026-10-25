# Open WebUI · Ivy Bridge AVX1

[English](README.md) · [Русский](README.ru.md) · [Upstream](https://github.com/open-webui/open-webui) · [Releases](https://github.com/aktalascloud/open-webui-ivybridge-avx1/releases/latest)

Windows build for Ivy Bridge. Extended Russian UI and menus.

Download the latest ZIP, extract it and run `Install.cmd`.

## Changes

- Current upstream: MCP protocol 2026-07-28 [#33087](https://github.com/open-webui/open-webui/pull/33087), deterministic tool schemas [#33000](https://github.com/open-webui/open-webui/pull/33000), batched chat-access checks [#32888](https://github.com/open-webui/open-webui/pull/32888). Real SDK tests cover discovery and legacy HTTP.
- MCP arguments with alternative schemas: [#32903](https://github.com/open-webui/open-webui/pull/32903). Readable errors: [#32942](https://github.com/open-webui/open-webui/pull/32942).
- Backend sharing permissions: [#32991](https://github.com/open-webui/open-webui/pull/32991), adapted without changing positional database arguments.
- Filter/bridge compatibility, microphone provenance, bounded speech and packaged Chromium checks. [Full patch list](.avx1/PATCHES.json).

## Evidence

Four explicit `ivybridge` profiles were tested: SSE4.2/AVX/F16C/POPCNT, O2/O3, Fat/ThinLTO and codegen units 1/8. AVX2/FMA/PGO/fast-math stay disabled. Best mixed JSON CPU result: **+0.40%**, with a **−5.42%** tool-schema serialization regression. Stock `orjson` remains the default. All 23 compatibility vectors match. These are JSON CPU tests, not LLM tokens/s. [Raw samples and flags](.avx1/measurements/ivy-flags-20261024.json).

[Hardware profile](.avx1/hardware-profile.json): installed PyTorch 2.14 is a CPU wheel. The separate source-build profile uses CUDA 12.9 and `sm_61`; it does not rebuild a vendor wheel.

Original licenses/notices and source history are preserved. Exact corresponding source is linked from each release. Credentials, logs, models and private filter/bridge code stay outside the public packages.

[PR/fork review: accepted and deferred changes](.avx1/review-20261025.json).
