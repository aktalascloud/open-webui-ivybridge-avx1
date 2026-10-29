# Open WebUI · Ivy Bridge AVX1

Strata composer control: standard reasoning levels, separate Ultra, and task-based Adaptive using the pinned MIT Mnemosyne selector. It routes the reasoning half of paired profiles; the second answer-style block is not injected. Only enrolled DavidAU Qwen3.8-Next aliases opt in; Swift is excluded. Standard sampling stays available for other models; template text and shared memory are not bundled.

[English](README.md) · [Русский](README.ru.md) · [Upstream](https://github.com/open-webui/open-webui) · [Releases](https://github.com/aktalascloud/open-webui-ivybridge-avx1/releases/latest)

Windows build for Ivy Bridge. Extended Russian UI and menus.

Download the latest ZIP, extract it and run `Install.cmd`.

## DSW2API · DeepSeek latest

Choose **DSW2API** from the normal provider list under Admin Settings → Connections. Sign in through the installed system browser; one shared Cline + OWUI extension keeps the existing browser profile and the Cline extension ID. Separate Native Messaging channels send the session only to the selected application after consent; passwords and Google cookies are never read. No token copying or debugging port is needed.

The separate OpenAI-compatible endpoint is `/dsw2api/v1`, model `deepseek-latest`. Use the local gateway key shown in the connection, never a DeepSeek cookie as an API key. There are no local RPM/daily quotas or older-model fallbacks. This is an unofficial web integration: DeepSeek controls availability, account rules and upstream throttling. No unlimited-service guarantee or paid-API fallback is implied.

OWUI registers its own local bridge automatically. Once, load the unpacked shared extension from `%LOCALAPPDATA%\OWUI DeepSeek Browser Bridge\extension` in your browser. Its Cline ID stays unchanged; the Cline installation is preserved.

Deep thinking and native DeepSeek smart search default to enabled; explicit request-level disabling takes priority.

Dependencies are included in the package metadata. The current web model follows DeepSeek's latest web deployment; the provider does not pretend that a different or older model is the latest.

## Changes

Security: Authlib 1.9.1 replaces vulnerable 1.7.2; seven advisory IDs and the exact regression scope are listed in `.avx1/PATCHES.json`.

Upstream fixes: sub-agent partial output (#33269), photo delegation (#33244), safer remote fetch (#33271), ComfyUI failures (#33237), IME input (#33245), accessible messages and note pages. Added Russian page menus and targeted migration/permission checks.

- Current upstream: MCP protocol 2026-07-28 [#33087](https://github.com/open-webui/open-webui/pull/33087), deterministic tool schemas [#33000](https://github.com/open-webui/open-webui/pull/33000), batched chat-access checks [#32888](https://github.com/open-webui/open-webui/pull/32888). Real SDK tests cover discovery and legacy HTTP.
- MCP arguments with alternative schemas: [#32903](https://github.com/open-webui/open-webui/pull/32903). Readable errors: [#32942](https://github.com/open-webui/open-webui/pull/32942).
- Backend sharing permissions: [#32991](https://github.com/open-webui/open-webui/pull/32991), adapted without changing positional database arguments.
- Filter/bridge compatibility, microphone provenance, bounded speech and packaged Chromium checks. [Full patch list](.avx1/PATCHES.json).

## Evidence

Four explicit `ivybridge` profiles were tested: SSE4.2/AVX/F16C/POPCNT, O2/O3, Fat/ThinLTO and codegen units 1/8. AVX2/FMA/PGO/fast-math stay disabled. Best mixed JSON CPU result: **+0.40%**, with a **−5.42%** tool-schema serialization regression. Stock `orjson` remains the default. All 23 compatibility vectors match. These are JSON CPU tests, not LLM tokens/s. [Raw samples and flags](.avx1/measurements/ivy-flags-20261024.json).

KB metadata query on this CPU: **94.76% fewer process CPU cycles**, median **94.1 → 4.96 ms**, on an in-memory SQLite fixture of 160 files × 128 KiB extracted text. Full text materialized: 20 MiB → 0. Query/DTO workload only, not LLM tokens/s. [Raw samples and exact methods](.avx1/measurements/kb-projection-20261029.json).

[Hardware profile](.avx1/hardware-profile.json): installed PyTorch 2.14 is a CPU wheel. The separate source-build profile uses CUDA 12.9 and `sm_61`; it does not rebuild a vendor wheel.

Original licenses/notices and source history are preserved. Exact corresponding source is linked from each release. Credentials, logs, models and private filter/bridge code stay outside the public packages.

[PR/fork review: accepted and deferred changes](.avx1/review-20261025.json).
