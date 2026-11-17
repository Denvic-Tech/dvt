# Отчёт об этапе 07: Каталог релизов и атомарная готовность Distributor

- **Статус:** `READY_FOR_REVIEW`
- **Задание:** [task.md](task.md)
- **Режим:** `IMPLEMENT`

## 1. Что сделано

- Distributor публикует API `GET /api/v1/dvt/releases`, `GET /api/v1/dvt/releases/{version}/manifest` и ссылку с точным digest. Поддерживаются stable/RC, обе формы RC, фильтры платформы, дистрибутива и исходной версии/ревизии.
- Писатель CI перед commit проверяет e2e receipt на соответствие точному конверту, доверие Ed25519, Git-тег (backend SHA и UI gitlink), фактически выдаваемые через HTTPS Compose и bootstrap, полный набор Compose и скачивание всех слоёв образов через клиентский Registry. Старый офлайн-каталог по-прежнему использует прежний кеш Git и Registry; API расширений обособлен.
- Готовность фиксируется одной условной записью S3 по нормализованной версии и формату. Запись содержит точные байты манифеста. Повтор совпадающего набора идемпотентен, следующий commit с другим содержимым запрещён, частично доставленный набор скрыт.
- Мастер читает настроенный Distributor по HTTPS, строит только достижимые пути от фактических источников и изолирует RC за подтверждением. Перед выбором он сверяет полученные или сохранённые байты с pin, актуальной политикой ключей и подписанным переходом. Кеш хозяина хранит дату; недоступность каталога не затрагивает рабочий DVT или журнал. Подготовка может прочитать тот же pin из защищённого кеша и повторно проверяет его перед записью в staging.

## 2. Изменённые файлы

| Репозиторий и путь | Что изменено |
| --- | --- |
| Distributor: `services/dvt_distribution/releases/{manifest,store,router,publish}.py`, `signed_release.v1.json` | Верификация общего v1, хранилище готовности, публичные GET и служебный CLI |
| Distributor: `services/dvt_distribution/{main,settings}.py`, `README.md`, `requirements.txt`, `docker-compose.dev.yaml` | Подключение каталога, параметры бакета и доверия, инструкции писателю и совместимость |
| Distributor: `services/offline_download/infra/{compose,git_files,registry}.py` | Общий разбор Compose и точные проверки Git и Registry без legacy cache |
| Distributor: `tests/services/dvt_distribution/test_dvt_releases.py`, `staging_*`; `tests/services/offline_download/test_git_compose.py` | Тесты условной публикации, фильтров, слоёв и происхождения; публичный fixture DVT |
| DVT: `services/installation_manager/{host_bootstrap,candidate_api,catalog_api}.py`, `release_catalog.md` | Источник конфигурации bootstrap, защищённый API, наблюдение Gateway/PostgreSQL, параметры TLS и trust |
| DVT: `services/installation_manager/application/{release_catalog,verified_staging}.py`, `infrastructure/catalog_files.py` | Подбор и верификация перехода, защищённый датированный кеш, неизменяемый pin staging |
| DVT: `tests/unit/services/installation_manager/{test_candidate.py,application/test_release_catalog.py}`, `AGENTS_CHANGELOGS.md` | Сценарии кэша, путей, отказа доверия и проверки защищённого API; русский changelog |

## 3. Критерии приёмки

| Критерий | Статус | Подтверждение |
| --- | --- | --- |
| SAC-01 | PASS | Фильтры HTTP проверены на stable/RC, архитектуре, дистрибутиве, исходной версии и ревизии. До успешного e2e receipt и delivery proof каталог пуст; отсутствие bootstrap либо Registry слоя блокирует commit. |
| SAC-02 | PASS | Python и реальный MinIO проверили конфликт конкурентных commit, идемпотентный повтор, точные исходные байты и 404 на чужой digest. Локальный Git-тег переставлен: строгая проверка SHA отклонила новый commit, legacy cache остался прежним. Неверная Ed25519 подпись отвергнута. |
| SAC-03 | PASS | Linux HTTPS/curl и тесты мастера подтвердили дату сохранённого каталога и повтор того же pin без доступа к Distributor. Повтор с отозванным ключом и выбор без настроенного verifier заблокированы; неверная наблюдаемая ревизия не создаёт путь. |

## 4. Проверки

У всех Python-команд `PYTHONPATH` установлен в абсолютный корень соответствующего checkout; запуск через `.venv/Scripts/python.exe`.

| Команда / проверка | Результат | Детали |
| --- | --- | --- |
| Distributor: `-m pytest -q -p no:cacheprovider --basetemp tmp/stage07/distributor-final2 tests/services/dvt_distribution tests/services/offline_download --tb=short` | PASS | 113 passed. `TEMP` и `TMP` указывают в `tmp/stage07`; для Git дочерний Windows `sh.exe` запущен после одобрения локальной команды. |
| DVT: `-m pytest -q -p no:cacheprovider tests/unit/services/installation_manager --tb=short` | PASS | 108 passed, 6 Linux-only skipped. |
| DVT Ruff по затронутым Python-файлам, Distributor Ruff `--isolated` и `-m services.dvt_distribution.releases.publish --help` | PASS | Проверены код мастера, модуль публикации, новые тесты и совместно используемые адаптеры. |
| Независимый стенд: FastAPI + MinIO, TLS/curl, Skopeo с HTTPS Registry, сверка JSON Schema | PASS | [Очищенная сводка](artifacts/contract-checks.md). |
| Публичная публикация, product e2e и потребитель CI | NOT_RUN | Запланированы для этапа 10; публичные адреса и действующие окружения не изменялись. |

## 5. Известные ограничения и риски

- Доступность комплекта удостоверяется при регистрации. Писатель должен хранить файлы по неизменяемым ключам и удерживать образы по digest, а хранилище готовности должно запрещать перезапись/удаление в обход условного Put. При недоступности файла позднее исполнитель отклонит отсутствующие или изменённые байты.
- Полная проверка Registry требует клиентского чтения всех слоёв и места на один образ в scratch. Служебная запись требует точного e2e receipt от доверенной задачи CI с отдельными правами; публичную подпись манифеста и receipt нельзя подменять утверждением от внешнего клиента.
- Для мастера используется Linux-платформа текущего beta-bootstrap; тип и версия дистрибутива сохраняются из `/etc/os-release`. После обновления ОС нужно заново запустить bootstrap с параметром каталога. Staging по-прежнему проверяет фактическую ОС и среду.
- UI и допуск операции будут использовать этот контракт в 09. Stage 07 не создаёт операцию при выборе, не добавляет production trust и не меняет прежнюю схему доступности legacy/extension API.

## 6. Вопросы мастер-агенту

Нет. Для этапа 10 контракт писателя и необходимые права описаны в README Distributor; для 09 — protected API в `services/installation_manager/release_catalog.md`.

## 7. Артефакты

- [artifacts/contract-checks.md](artifacts/contract-checks.md) — очищенные результаты независимых контрактных проверок.

## 8. Итерации исправлений

Пока нет. Замечания во время реализации учтены до передачи на ревью.
