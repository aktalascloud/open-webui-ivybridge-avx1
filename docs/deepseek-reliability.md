# DeepSeek reliability / Надёжность DeepSeek

This unofficial web integration cannot guarantee that DeepSeek will not restrict an account. Upstream limits and account rules apply. A restriction is never removed by restarting, switching identities, disguising traffic or replaying a failed request.

Неофициальная веб-интеграция не гарантирует отсутствие ограничений аккаунта. Действуют правила DeepSeek. Перезапуск и повтор запроса не снимают блокировку.

The managed integration uses one shared cross-client request lease and one upstream request at a time, delta prompts for reused conversations, a 1800-second session cache, no background login/recovery probes and no automatic replay after rate limits, empty responses or uncertain outcomes. Vendor restrictions and expired authorization persist in the encrypted private account store. Explicit browser consent is required for session renewal. There are no added daily or RPM quotas.

Используются общая очередь Cline/OWUI, один запрос за раз, передача новой части истории и кэш сессии на 1800 секунд. Автоматические повторные отправки и фоновые проверки входа отключены. Обнаруженная блокировка и истёкшая авторизация сохраняются в закрытом зашифрованном хранилище. Продление сессии требует явного действия в обычном браузере. Суточные/RPM-квоты не добавляются.

Evidence: offline managed-adapter no-replay, encrypted restart, account isolation and process-lease fixtures. No live vendor inference or authorization was used to test these changes.

Sources: [anti-flood PR11](https://github.com/snake-aabb-wtf/deepseek-web2api-free/pull/11), [upstream account warning18](https://github.com/snake-aabb-wtf/deepseek-web2api-free/issues/18), [DeepSeek Terms](https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html).
