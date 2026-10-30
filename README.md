# Open WebUI · Ivy Bridge AVX1

Strata composer control: standard reasoning levels, separate Ultra, and task-based Adaptive using the pinned MIT Mnemosyne selector. It routes the reasoning half of paired profiles; the second answer-style block is not injected. Only enrolled DavidAU Qwen3.8-Next aliases opt in; Swift is excluded. Standard sampling stays available for other models; template text and shared memory are not bundled.

[English](README.md) · [Русский](README.ru.md) · [Upstream](https://github.com/open-webui/open-webui) · [Releases](https://github.com/aktalascloud/open-webui-ivybridge-avx1/releases/latest)

Windows build for Ivy Bridge. Extended Russian UI and menus.

Download the latest ZIP, extract it and run `Install.cmd`.

## Changes

Security: Authlib 1.9.1 replaces vulnerable 1.7.2; seven advisory IDs and the exact regression scope are listed in `.avx1/PATCHES.json`.

Upstream 0.12.5/dev: chat-load race fixes [#33377](https://github.com/open-webui/open-webui/pull/33377), higher default tool-iteration budget [#33384](https://github.com/open-webui/open-webui/pull/33384), smaller KB mutation responses [#33335](https://github.com/open-webui/open-webui/pull/33335), and OpenAPI tool listings [#33205](https://github.com/open-webui/open-webui/pull/33205). Preserves MCP/browser isolation and adds 18 Russian labels. MCP Apps use a sandboxed iframe with explicit tool-call confirmation.

- Current upstream: MCP protocol 2026-07-28 [#33087](https://github.com/open-webui/open-webui/pull/33087), deterministic tool schemas [#33000](https://github.com/open-webui/open-webui/pull/33000), batched chat-access checks [#32888](https://github.com/open-webui/open-webui/pull/32888). Real SDK tests cover discovery and legacy HTTP.
- MCP arguments with alternative schemas: [#32903](https://github.com/open-webui/open-webui/pull/32903). Readable errors: [#32942](https://github.com/open-webui/open-webui/pull/32942).
- Backend sharing permissions: [#32991](https://github.com/open-webui/open-webui/pull/32991), adapted without changing positional database arguments.
- Filter/bridge compatibility, microphone provenance, bounded speech and packaged Chromium checks. [Full patch list](.avx1/PATCHES.json).

## Evidence

Four explicit `ivybridge` profiles were tested: SSE4.2/AVX/F16C/POPCNT, O2/O3, Fat/ThinLTO and codegen units 1/8. AVX2/FMA/PGO/fast-math stay disabled. Best mixed JSON CPU result: **+0.40%**, with a **−5.42%** tool-schema serialization regression. Stock `orjson` remains the default. All 23 compatibility vectors match. These are JSON CPU tests, not LLM tokens/s. [Raw samples and flags](.avx1/measurements/ivy-flags-20261024.json).

KB metadata query on this CPU: **94.76% fewer process CPU cycles**, median **94.1 → 4.96 ms**, on an in-memory SQLite fixture of 160 files × 128 KiB extracted text. Full text materialized: 20 MiB → 0. Query/DTO workload only, not LLM tokens/s. [Raw samples and exact methods](.avx1/measurements/kb-projection-20261029.json).

[Hardware profile](.avx1/hardware-profile.json): installed PyTorch 2.14 is a CPU wheel. The separate source-build profile uses CUDA 12.9 and `sm_61`; it does not rebuild a vendor wheel.

Original licenses/notices and source history are preserved. Exact corresponding source is linked from each release. Credentials, logs, models and private filter/bridge code stay outside the public packages.

[PR/fork review: accepted and deferred changes](.avx1/review-20261030.json).

[FreeLLM](docs/provider-eligibility.md): three anonymous cloud models from Reflection, Poolside and NVIDIA; no personal API key/account, shared200 requests/hour/IP. DSW2API/browser integration stays removed.

Avatar update: full-body Conduit voice view and a private 100 MiB VRM cache; avatars stay on your OWUI server, never inside the APK. New uploads: 20 MiB, source textures up to 8K; display memory is bounded. Existing audio routing is preserved.
