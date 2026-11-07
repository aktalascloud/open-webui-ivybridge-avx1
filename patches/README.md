# Applied downstream patches: webui

Only currently applied maintainer differences from the exact official baseline are included.
Содержит только текущие применённые нами отличия от указанного официального upstream.
Mainstream-only commits, rejected proposals and reverted experiments are excluded.
Коммиты самого mainstream, неприменённые предложения и отменённые эксперименты исключены.

Official baseline: `055bd98f3a223cadd8be381422238ca9410cc9db`. Downstream snapshot: `950aff1a53382a5831a304040c34681d04b93f86`.
Patches are already applied in this fork. Apply `series` only to a clean checkout of that exact baseline.
В этом форке патчи уже применены. `series` предназначен только для чистого checkout указанной базы.
Files are grouped by purpose; manifest.json records paths, hashes and the exact reconstructed tree.

Assistant microphone/voice/VRM hooks, Strata/FreeLLM controls, scoped tool policy and protected browser handoff, plus fork dependency and locale adaptations.

| Patch | Description | Files |
|---|---|---|
| [01-runtime.patch](01-runtime.patch) | Local runtime, integration, security, dependency and platform adaptations / Наши изменения работы, интеграций, безопасности и платформ. | 61 |
| [02-build.patch](02-build.patch) | Our reproducible build, toolchain and CI recipes / Наши сборочные рецепты, toolchain и CI. | 35 |
| [03-tests.patch](03-tests.patch) | Our regressions and adaptations of upstream fixtures / Наши регрессии и адаптации тестов. | 32 |
| [04-documentation.patch](04-documentation.patch) | Our fork documentation, notices and qualification evidence / Наши описания форка, уведомления и доказательства квалификации. | 6 |
