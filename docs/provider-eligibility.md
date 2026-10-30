# Optional cloud providers / Облачные провайдеры

Checked 2026-10-30. Inclusion requires **no payment, registration, personal API key, or usage quota**. Unknown limits do not qualify. No cloud model currently meets all four requirements; no fictitious model, hidden paid fallback, extra router or account registration is installed.

Проверено 30.10.2026. Для подключения одновременно требуются **бесплатность, отсутствие регистрации, личного API-ключа и квот**. Неизвестные лимиты не считаются безлимитом. Подтверждённых облачных моделей пока нет; фиктивный каталог, платный fallback и лишний роутер не добавлены.

| Source / Источник | Finding / Результат |
| --- | --- |
| [DSH Desktop](https://github.com/dataelement/dsh-desktop/tree/7eac110fd516908771e4026bdb46a5ac92eae456) | Harness host, not an inference service; API-key or account authentication. Оболочка Harness; требует ключ или аккаунт. |
| [Free-LLM](https://github.com/nejib1/Free-LLM/tree/29d15d5af1e528e92f05ac268669d1e891944132) | Directory includes finite free tiers and trials. Каталог бесплатных тарифов и пробных квот. |
| [FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi/tree/36826e7cfe9ba281d5815e865045f1333b598f13) | Router aggregates provider keys and finite budgets; total tokens are not unlimited access. Роутер ключей и конечных квот; сумма токенов не означает безлимит. |

Anonymous exceptions were checked: [Kilo](https://kilo.ai/docs/gateway/usage-and-billing) limits free use to 200 requests/hour/IP; [OVH](https://docs.ovhcloud.com/en/guides/public-cloud/ai-machine-learning/ai-endpoints-troubleshooting) to 2 requests/minute/IP/model. [AI Horde](https://github.com/Haidra-Org/AI-Horde/blob/main/horde/apis/v2/kobold.py) has request throttling; its FreeLLMAPI adapter does not implement tool calling. [FreeModel](https://freemodel.online/) requires a key and routes over finite quotas, including paid candidates. None qualifies under this policy.

Проверены и анонимные варианты: Kilo — 200 запросов/час/IP; OVH — 2 запроса/минуту/IP/модель; AI Horde ограничивает частоту, а адаптер не поддерживает tool calling. FreeModel требует ключ и использует конечные квоты, включая платные каналы. Эти варианты исключены.

DSW2API and the OWUI browser connector were removed at the user's request. Existing chats, model metadata, ACLs, local providers and stock audio are preserved. Cline and the installed DSH Desktop are independent and unchanged by this integration. Research never sends private prompts or credentials to candidate services.

DSW2API и браузерный коннектор OWUI удалены по запросу. История, метаданные моделей, ACL, локальные подключения и штатный звук сохранены. Cline и установленный DSH Desktop независимы; эта интеграция их не меняет. Исследование не отправляет кандидатам личные запросы и ключи.
