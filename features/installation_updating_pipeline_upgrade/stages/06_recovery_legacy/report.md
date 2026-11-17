# Отчёт об этапе 06. Продолжение, восстановление и legacy

- **Статус** `READY_FOR_REVIEW`
- **Задание** [task.md](./task.md)
- **Режим** `IMPLEMENT`

## 1. Что сделано

- Подготовка обычного UPDATE отклоняет выбор более раннего релиза до загрузки образов. В окне обслуживания доступны отмена подготовки, продление и отсрочка. До вмешательства в схему можно вернуть прежний комплект. Исполнитель проверяет текущие ID и digest контейнеров, привязку PostgreSQL, ревизию, копию при её наличии и готовность. Открытие замороженного gate связано с записью в PostgreSQL.
- При продолжении миграции учитываются живая ревизия PostgreSQL, запись `core/done/resumed`, работающий мигратор и advisory lock. Восстановление совместимого мастера с прежним адресом и тем же ID операции можно запустить отдельно. Отказ остаётся в истории.
- Старый bootstrap получает защищённый opt-in. Наблюдение сопоставляет фактические Docker IDs, registry digests, ревизию, проект, реплики и привязки с утверждённым predecessor и сохранённой моделью. При наличии admission v1 и подписанного маршрута можно заменить только управление, сохранив UUID экземпляра и работающие роли приложения. На старых сборках без admission v1 новый путь остаётся закрыт.
- Переносимая копия сохраняет конфигурацию, исходную учётную запись PostgreSQL, identity, файлы, журнал и расширения. Подготовка требует отдельно подтвердить digest и UTC-время потери изменений. Файлы восстанавливаются в отдельное дерево, PostgreSQL поднимается без сети и портов. Дерево публикуется после сверки, gate остаётся frozen. На чистом хосте старый закреплённый комплект получает отдельную запись об успешно восстановленной схеме с физической identity новой БД. Прежний доступ, проект, список расширений, роли и публичный URL проверяются до открытия приёма.
- Диагностика по ID доступна через авторизованный мастер. Она возвращает типизированные причины, события и наблюдения с ограниченным объёмом и без сырых журналов Docker. Можно привезти отдельный очищенный отчёт об исходном отказе после времени копии. Необратимое удаление данных требует отдельного плана и явного подтверждения канонического пути.

## 2. Изменённые файлы

| Путь | Изменение |
| --- | --- |
| `services/installation_manager/application/legacy_transition.py`, `legacy_adopt.py` | Наблюдение и исполнитель защищённого перехода со старого bootstrap |
| `services/installation_manager/application/portable_restore.py`, `restore_runtime.py` | План и подтверждение потери, перенос данных, новая физическая identity и проверка восстановленного приложения |
| `services/installation_manager/application/application_apply.py`, `recovery.py`, `verified_staging.py` | Матрица действий, продолжение по наблюдаемому результату, запрет обычного downgrade, возврат старого комплекта и мастера |
| `services/installation_manager/infrastructure/application_host.py`, `maintenance_archive.py`, `maintenance_database.py`, `operation_store.py` | Сверка системных наблюдений и артефактов, запись открытия gate, выборка событий |
| `services/installation_manager/candidate_api.py`, `candidate_executor.py`, `candidate_main.py`, `host_bootstrap.py` | Авторизация, запуск действий по ID и повтор после смены владельца |
| `services/installation_manager/frontend/src/CandidateApp.jsx`, `services/installation_manager/recovery.md` | Действия и диагностика в мастере, команды оператора |
| `uninstall.sh` | План scoped Compose ресурсов, отдельное подтверждение удаления данных |
| `tests/unit/services/installation_manager/`, `tests/unit/services/gateway/test_lifespan_sessions.py`, `AGENTS_CHANGELOGS.md` | Регрессии, проверка синхронного барьера Gateway и запись изменений |

## 3. Критерии приёмки

| Критерий | Статус | Что проверено |
| --- | --- | --- |
| SAC-01 | `PASS` | Историческая цепочка на Debian прошла. Наблюдаемые 1.23.0, `0063` и десять digest остались прежними при `DVT_VERSION=9.99.0`. На Ubuntu положительный opt-in `1.25.0-rc4/0070` сохранил UUID экземпляра, журнал, `.env`, bind и все контейнеры приложения/PostgreSQL. |
| SAC-02 | `PASS` | Unit проверяет смену владельца и решения до миграции, при активной блокировке, после core и после подтверждения целевой схемы, а также fallback мастера на том же bind. Для реального падения Proxy с кодом 42 сохранён `verifying/profile_unhealthy`. На другом хосте проверены тот же ID, новый receipt и прежняя привязка мастера. |
| SAC-03 | `PASS` | Более ранний подписанный релиз отклонён до загрузки. На чистом Debian из замороженной копии Ubuntu восстановлены `0070`, исходные вход, проект, расширение, файл и порты. Неверное подтверждение времени отклонено до публикации данных, post-copy файл отсутствует. После штатного resume выполнены ETL `SUCCESS` и scoped MCP. Подготовка данных 4,017 с, готовность и auth/resume 76,984 с. |
| SAC-04 | `PASS` | Unit подтверждает авторизацию и ограничение диагностики, отсутствие конфиденциального вывода, сохранение исходных аварийных событий и отказ проверки при повреждении. Содержимое копии проверяется до публикации дерева, а при невозможности функциональной проверки запись gate остаётся frozen. |

## 4. Проверки

| Проверка | Статус | Детали |
| --- | --- | --- |
| `python -m pytest -q -p no:cacheprovider tests/unit/services/installation_manager tests/unit/services/gateway/update_runtime` | `PASS` | Фокусный прогон с проверками legacy, restore, downgrade и диагностики — 123 passed, 6 skipped. |
| `python -m pytest -q -p no:cacheprovider --tb=short tests/unit/services/installation_manager tests/unit/services/gateway` | `FAIL` | Итог 791 passed, 6 skipped, 1 failed. `test_list_extensions_serializes_record` падает на `ExtensionRecord.catalog_versions`, дефект воспроизводится на архиве `d25a1e5`. Другая ошибка первого прогона, `test_lifespan_uses_shared_async_session_factory`, исправлена проверкой обязательного schema barrier в том же sync Session перед async startup. |
| `npm run build` в `services/installation_manager/frontend` | `PASS` | 37 modules, JS 159.54 kB. Первичный sandbox run получал EPERM от Vite на realpath; локальная сборка с разрешением прошла. |
| Ruff по изменённым Python-файлам и fixture | `PASS` | `All checks passed!` |
| `bash -n uninstall.sh` и `uninstall.sh --plan --delete-data` | `PASS` | Read-only план на действующем fixture показал 11 контейнеров. Их IDs, хеши Compose, `.env` и копии сохранились. |
| Исторический DVT на Debian 13 amd64, Docker 29.10 / Compose 5.7.1 | `PASS` | `1.22.0/0061 → 1.23.0/0063 → 1.24.0-rc2/0068`. Реальные закреплённые образы, прежние пользователь, проект, identity и файл, контрольный ETL `SUCCESS` и project-scoped AI MCP `list_projects`. Ручная изолированная последовательность Compose с закреплёнными digest и встроенной миграцией Gateway. Старый HTTP updater этим прогоном не вызывался. |
| Read-only legacy-план и изменение `DVT_VERSION` | `PASS` | Проект `dvt`, активный Gateway 1.23.0, `0063`, десять ролей по digest, binds 127.0.0.1:18146 и 127.0.0.1:19146, сеть `dvt-net`, один worker. В отчёте появился `saved_version_differs`; сохранились `no_signed_transition` и `source_has_no_admission_guard`. |
| `portable_restore_smoke.py create/verify`, Debian 13 → Ubuntu 24.04 amd64 | `PASS` | 4 закрытых fixture-файла, 20 480 байт, ревизия `0070`, перенос и верификация базы 3489 мс. Прежний пароль PostgreSQL, файлы, файл расширения, identity и журнал подтверждены, терминальная задача сохранилась, запись после копии отсутствует. Приём остался frozen. |
| Реальный Stage 05 INSTALL на Ubuntu 24.04 с test-signed комплектом | `PASS` | `55f39bec-df68-45fd-8336-d958ad1fe5bb`, ревизия `0070`. Реальные backend/infra образы `d25a1e5`, опубликованный UI 1.24.0-rc2, включён AI MCP. Подтверждены вход, проект, установленное расширение, постоянный файл, ETL и MCP. Это исходная сторона прикладного restore. |
| Реальное восстановление Ubuntu 24.04 → чистый Debian 13 | `PASS` | `dc78e2d4-3ddc-455a-9320-33ca72912d1b`, копия 153 600 байт, `2026-11-16T16:19:24.221262+00:00`, `sha256:f656151f6606227c735bbadeeb58c7a5e5fa4521e3d0339a003eb0f02be38af9`. Снова доступны прежние login, проект, расширение, файл и порты. Исходный `profile_unhealthy` сохранён, task gate открылся после подтверждений. ETL `SUCCESS` и MCP `list_projects` через Proxy. Доставка закреплённых образов и подготовка внешнего bridge выполнены отдельными шагами. |
| Guarded opt-in со старого bootstrap на Ubuntu 24.04 | `PASS` | `d7114027-ea83-40e6-8506-59ef8e2097b6`, test-signed `1.25.0-rc4/0070`, `sha256:b755420ec377136fabcf6e4dcc3064dcec6a8843c0ea7f319bccfbcb27e91939`. Приложение и PostgreSQL сохранили контейнеры. Мастер перезапущен в защищённом режиме на прежнем 127.0.0.1:19150. Identity, журнал и исходные байты `.env` подтверждены. |
| Принудительная перезагрузка хоста на нескольких стадиях | `NOT_RUN` | Повтор и смена владельца покрыты unit; прогон Ubuntu → Debian отдельно подтвердил чтение замороженной копии и завершение операции на новом хосте. |

## 5. Ограничения

- Выполняемый opt-in относится к совместимому старому bootstrap, уже использующему приложение с admission v1. Переход guardless исторических приложений через новый путь не заявлен.
- Получатель сохраняет исходный абсолютный путь, bind и Compose project. Для внешней сети экземпляра оператор восстанавливает соответствующую инфраструктуру отдельно.
- Скопированный журнал содержит историю до создания снимка. Если исходный диск потерян и отдельного защищённого экспорта исходного отказа нет, послекопийная история недоступна.
- В прикладных тестах использованы реальные backend/infra образы из `d25a1e5` и опубликованный UI 1.24.0-rc2. Это проверка поведения на тестовом подписанном комплекте. Сборка UI из актуального gitlink на 4 ГиБ не завершилась, поэтому релизный комплект проверяется отдельно.

## 6. Вопросы мастер-агенту

- Нет. Сохранённые ограничения сценариев отражены выше.

## 7. Артефакты

- [portable_restore_smoke.py](./artifacts/portable_restore_smoke.py) — двуххостовый перенос копии с реальным PostgreSQL и синтетическими данными без открытых портов.
- [portable-smoke-result.json](./artifacts/portable-smoke-result.json) — очищенный результат этого прогона.
- [legacy_guarded_smoke.py](./artifacts/legacy_guarded_smoke.py) — сценарий для изолированного подписанного guard-capable fixture.
- [full-restore-result.json](./artifacts/full-restore-result.json) — очищенные результаты прикладного восстановления Ubuntu → Debian.
- [legacy-adoption-result.json](./artifacts/legacy-adoption-result.json) — очищенные результаты положительного перехода на Ubuntu.

## 8. Итерации исправлений

Пока нет.
