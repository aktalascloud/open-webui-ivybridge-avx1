# Applied downstream patches: webui

Only currently applied maintainer differences from the exact official baseline are included.
Содержит только текущие применённые нами отличия от указанного официального upstream.
Mainstream-only commits, rejected proposals and reverted experiments are excluded.
Коммиты самого mainstream, неприменённые предложения и отменённые эксперименты исключены.

Official baseline: `782f4b705fc6de807ff6aa1a235ea46dcc982057`. Downstream snapshot: `f89c4a413260134447bd5b432d7ebf5a20551746`.
Patches are already applied in this fork. Apply `series` only to a clean checkout of that exact baseline.
В этом форке патчи уже применены. `series` предназначен только для чистого checkout указанной базы.
Apply the numbered patches in the order listed in `series`. Each row describes one topic.
Накладывайте патчи в порядке файла `series`. Изменения в общих файлах остаются вместе.
The manifest records each patch’s exact file list and SHA256.

Assistant microphone/voice/VRM hooks, Strata/FreeLLM controls, scoped tool policy and protected browser handoff, plus fork dependency and locale adaptations.

| Order | Patch | Description | Files |
|---:|---|---|---:|
| 1 | [01-dependencies.patch](01-dependencies.patch) | Pin compatible Python and frontend dependencies, including OAuthlib 4.0.1 / Закрепляет совместимые зависимости и исправленный OAuthlib 4.0.1. | 14 |
| 2 | [02-free-llm.patch](02-free-llm.patch) | Add the FreeLLM provider catalog, request policy and connection preset / Добавляет каталог FreeLLM, правила запросов и шаблон подключения. | 8 |
| 3 | [03-strata-reasoning.patch](03-strata-reasoning.patch) | Add Strata reasoning controls and adaptive Mnemosyne profile selection / Добавляет настройки рассуждений Strata и адаптивный выбор профиля Mnemosyne. | 9 |
| 4 | [04-voice-avatars.patch](04-voice-avatars.patch) | Render model VRMs with bounded textures and wire voice call and avatar controls / Отображает VRM моделей с лимитами текстур и подключает настройки звонков и аватаров. | 11 |
| 5 | [05-protected-media.patch](05-protected-media.patch) | Load and download protected audio, video and files through authenticated requests / Загружает защищённые аудио, видео и файлы с авторизацией. | 8 |
| 6 | [06-terminal-browser-access.patch](06-terminal-browser-access.patch) | Bind browser and watch tickets to the terminal owner, token and chat scope / Привязывает браузерные и файловые билеты к владельцу терминала, токену и чату. | 5 |
| 7 | [07-tools-and-subagents.patch](07-tools-and-subagents.patch) | Scope tool discovery to selected IDs and resolve subagents under the caller’s access rights / Ограничивает инструменты выбранными ID и проверяет права вызывающего для субагентов. | 9 |
| 8 | [08-chat-integration.patch](08-chat-integration.patch) | Wire mic origin, voice budget, tool selection and model routing into shared chat and request handlers / Подключает источник микрофона, бюджет голоса, выбор инструментов и маршрутизацию моделей в общих обработчиках. | 22 |
| 9 | [09-localization.patch](09-localization.patch) | Translate fork controls and localize generated UI content / Переводит настройки форка и локализует содержимое интерфейса. | 5 |
| 10 | [10-native-json.patch](10-native-json.patch) | Qualify AVX1 orjson builds and native cache reuse, with stock JSON as default / Проверяет AVX1-сборки orjson и переиспользование кэша, оставляя штатный JSON по умолчанию. | 11 |
| 11 | [11-package-assets.patch](11-package-assets.patch) | Adjust WebUI package hooks, Vite build and bundled browser assets / Адаптирует упаковку WebUI, сборку Vite и ресурсы браузера. | 5 |
| 12 | [12-portable-install.patch](12-portable-install.patch) | Provide portable build commands and the fork installer / Добавляет команды переносимой сборки и установщик. | 4 |
| 13 | [13-ci-build.patch](13-ci-build.patch) | Pin toolchains and package inputs, and run the fork build and publication checks / Закрепляет инструменты и входы сборки, запускает проверки пакетов и публикации. | 10 |
| 14 | [14-upstream-regressions.patch](14-upstream-regressions.patch) | Exercise adapted upstream contracts and regression fixtures / Проверяет адаптированные контракты upstream и сценарии регрессий. | 5 |
| 15 | [15-project-docs.patch](15-project-docs.patch) | Document fork setup, support and license terms / Описывает установку, поддержку и условия лицензирования форка. | 2 |
| 16 | [16-fork-records.patch](16-fork-records.patch) | Record fork changes, upstream reviews and qualification measurements / Хранит журнал изменений, разбор upstream и результаты проверок. | 5 |
