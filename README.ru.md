# Open WebUI · Ivy Bridge AVX1

[English](README.md) · [Русский](README.ru.md) · [Исходный проект](https://github.com/open-webui/open-webui) · [Релизы](https://github.com/aktalascloud/open-webui-ivybridge-avx1/releases/latest)

Сборка Windows для Ivy Bridge. Дополнены русский интерфейс и меню.

Скачайте последний ZIP, распакуйте и запустите `Install.cmd`.

## Изменения

- Аргументы MCP со схемами альтернатив: [#32903](https://github.com/open-webui/open-webui/pull/32903); читаемые ошибки: [#32942](https://github.com/open-webui/open-webui/pull/32942).
- Серверная проверка прав на публикацию: [#32991](https://github.com/open-webui/open-webui/pull/32991), с сохранением позиционного аргумента БД.
- Совместимость фильтра/бриджа, микрофон, ограниченная озвучка и проверка готового интерфейса Chromium. [Все патчи](.avx1/PATCHES.json).

## Проверки и замеры

Проверены четыре профиля `ivybridge`: SSE4.2/AVX/F16C/POPCNT, O2/O3, Fat/ThinLTO и codegen units 1/8. AVX2/FMA/PGO/fast-math отключены. Лучший общий результат JSON: **+0,40%**, но сериализация схем инструментов медленнее на **5,42%**. По умолчанию сохранён обычный `orjson`. Все 23 проверки совместимости совпали. Это CPU-тесты JSON, не tokens/s LLM. [Исходные замеры и флаги](.avx1/measurements/ivy-flags-20261024.json).

[Профиль оборудования](.avx1/hardware-profile.json): установленный PyTorch 2.14 собран для ЦП. Отдельный профиль исходной сборки использует CUDA 12.9 и `sm_61`; готовый wheel от этих переменных не пересобирается.

Оригинальные лицензии, уведомления и история исходников сохранены. Точные исходники указаны в релизе. Ключи, логи, модели LLM и закрытый код фильтра/бриджа в публичные пакеты не входят.

[Ревью PR/форков: принятые и отложенные изменения](.avx1/review-20261024.json).
