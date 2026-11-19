# Open WebUI for Ivy Bridge · AVX1

[Русский](#русский) · [Release / Скачать](https://github.com/aktalascloud/open-webui-ivybridge-avx1/releases/tag/daily-20261118-97ef89ca) · [Guide / Документация](patches/README.md) · [Evidence / Данные](https://github.com/aktalascloud/open-webui-ivybridge-avx1/blob/97ef89cab11eb39ffd34a0183eefd5b7f45d83db/.avx1/measurements/latest.json) · [Upstream](https://github.com/open-webui/open-webui)

Self-host Open WebUI on older Windows x64 PCs. The Ivy Bridge build adds Russian localization and integrates agent tools, MCP and local model servers.

**Quick start.** Extract the Windows ZIP and run `Install.cmd`. For a source build, use `Build.cmd status` and `Build.cmd build` with Python 3.12+, Git and GitHub CLI. [Applied patches](patches/README.md).

**Evidence.** Five paired in-memory SQLite trials for the file listing path gave a median 92.08 → 4.98 ms on a 160-file fixture. This measures one query path with the source revisions listed in the report.

## Русский

Самостоятельный запуск Open WebUI на старых Windows x64. Сборка для Ivy Bridge добавляет русский интерфейс и интеграции с инструментами агентов, MCP и локальными серверами моделей.

**Запуск.** Распакуйте ZIP для Windows и запустите `Install.cmd`. Для сборки из исходников выполните `Build.cmd status` и `Build.cmd build` с Python 3.12+, Git и GitHub CLI. [Патчи](patches/README.md).

**Проверка.** В пяти парных тестах SQLite в памяти медиана получения списка из 160 файлов сократилась с 92,08 до 4,98 мс. Отчёт относится к одному пути запроса и содержит ревизии исходников.

[All projects / Все проекты](https://github.com/aktalascloud)
