# FreeLLM

One provider in OWUI → Connections. No account, personal API key, Cline, DSH Desktop or extra router. The current anonymous Kilo gateway has a **shared limit of 200 requests/hour/public IP**, across all three models and clients. Hourly limits were explicitly accepted by the user on 30 October 2026.

Один провайдер в OWUI → Подключения. Без аккаунта, личного API-ключа, Cline, DSH Desktop и лишнего роутера. Общий лимит анонимного Kilo — **200 запросов/час на публичный IP**, суммарно для трёх моделей и клиентов. Почасовой лимит согласован пользователем 30.10.2026.

| Model / Модель | Selection evidence / Основание выбора |
| --- | --- |
| Reflection Beam1.0 | [Official model card](https://reflection.ai/beam-model-card): coding, reasoning, MCP/tool use. |
| Poolside Laguna S2.1 | [Official report](https://poolside.ai/blog/introducing-laguna-s-2-1): long-horizon coding/tool workflows. |
| NVIDIA Nemotron3.5 Super VL | [Official model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4): reasoning, vision, long context. |

These are three distinct vendors, not three Nemotron variants. Selection is workload-based, not a universal intelligence ranking. All three passed one anonymous streaming tool-call probe; no private data was sent. Gateway-served precision and availability can change. No paid model or hidden retry/fallback is selected.

Три разных вендора, без повторов Nemotron. Выбор ориентирован на задачи пользователя и не объявляется универсальным рейтингом интеллекта. Каждая модель прошла анонимную потоковую проверку tool calling на искусственном запросе. Личные данные не отправлялись. Платный fallback и скрытый повтор запросов не включены.

**Privacy / Приватность:** providers may retain prompts/outputs for training; avoid personal/confidential data. Поставщики могут сохранять запросы и ответы для обучения; не передавайте конфиденциальные данные. [Gateway terms](https://kilo.ai/docs/gateway/models-and-providers) · [Quota](https://kilo.ai/docs/gateway/usage-and-billing).

Daily review checks the live free catalog and the sources [DSH Desktop](https://github.com/dataelement/dsh-desktop), [Free-LLM](https://github.com/nejib1/Free-LLM), [FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi), including relevant PR/issues/forks. Maintain one strongest qualified option per vendor, three vendors total; preserve the list when unchanged. Unverified, paid or account/key-required channels are not added. DSW2API/browser integration stays removed; existing local services/history/ACLs are preserved.

Ежедневно проверяются каталог и указанные источники, PR/issues/форки. По одному сильному проверенному варианту от каждого из трёх вендоров; неизменный список не требует пересборки. Платные каналы, обязательные аккаунты/ключи и неподтверждённые модели исключаются. DSW2API и браузерная интеграция не возвращаются; локальные сервисы, история и ACL сохранены.
