# Отчёт об этапе 08. Офлайн-архив из того же комплекта

- **Статус:** `READY_FOR_REVIEW`
- **Задание:** [task.md](task.md)
- **Режим:** `IMPLEMENT`

## 1. Что сделано

- Distributor закрепляет точные байты готового `SignedRelease`, проверяет Compose и bootstrap, экспортирует все уникальные digest ролей в OCI layout и подписывает USTAR inventory сертифицированным ключом релиза. В архив входят локальные пакеты Docker и выбранный профиль расширений. DCC продолжает использовать свой прежний источник.
- DVT проверяет доверенную цепочку и подпись архива, ограничивает чтение и распаковку, сверяет все члены со списком SHA-256 и размеров, проверяет платформу, OCI descriptor, config и слои. После загрузки проверяет локальный RepoDigest, leaf descriptor, image ID и слои. Compose запускается с `--pull never`.
- CLI закрепляет bundle ID и pin релиза в общем OperationStore. Подготовка выполняется через VerifiedStaging; применение обновления проходит через MaintenanceBackup и ApplicationApply. Восстановление продолжает путь portable_restore/RestoreRuntime после заполнения локального кэша. В резервную копию входят журнал, рабочие настройки и данные расширений. Повторно извлекаемый кэш OCI исключён из неё.
- Комплектность транзитивных wheels проверяется в целевых Gateway и Task Worker без подключения к сети. В строгом режиме pip использует только локальные wheels. Перед maintenance повторно проверяются доступность всех образов и профиль расширений.

## 2. Изменённые файлы

| Путь | Что изменено |
| --- | --- |
| `services/installation_manager/infrastructure/offline_bundle.py`, `offline_host.py` | Проверка подписи, USTAR, OCI, .deb, локального образа и wheelhouse |
| `services/installation_manager/application/offline_bundles.py`, `verified_staging.py`, `maintenance_backup.py`, `application_apply.py` | Приём, подготовка и применение с общим operation ID и блокировкой |
| `services/installation_manager/host_bootstrap.py`, `candidate_executor.py`, `infrastructure/staging_docker.py`, `infrastructure/maintenance_archive.py` | Локальный bootstrap, проверка мастера с числовым loopback и прежней TLS identity, Docker load, проверка wheels и исключение транспортного кэша из копии |
| `src/modules/extension_management/infra/dependency_manager.py`, `packages/{dependencies,installer,offline_check}.py` | Строгий локальный режим подготовки зависимостей |
| `scripts/offline/`, `tests/unit/scripts/offline/test_runner.py` | Совместимые CLI-входы и руководство оператору |
| `tests/unit/services/installation_manager/infrastructure/test_offline_bundle.py`, `tests/unit/src/modules/extension_management/infra/packages/test_dependencies.py` | Подпись, tamper, traversal, OCI digest/platform и строгие ограничения pip |
| Distributor `services/offline_download/` | Профиль, пин и Docker-пакеты, OCI export без преобразования digest, подпись и сборка DVT через ReadyRelease |
| Distributor `tests/services/offline_download/test_dvt_bundle.py` | ReadyRelease, Ed25519, целостность, имена deb с эпохой и OCI/Docker schema 2 |
| Distributor `services/offline_download_frontend/src/{App.jsx,api.js}` | Обычная форма DVT передаёт выбранные ОС, версию и профиль для обоих видов архива. |

## 3. Критерии приёмки

| Критерий из task.md | Статус | Подтверждение |
| --- | --- | --- |
| `SAC-01` | `PASS` | Тесты отклоняют неправильную подпись и pin, повреждённый/пропущенный файл, неожиданный образ, traversal, symlink/hardlink, повторы и другую ОС/роль. OCI alias и несовпадающие слои отклоняются. В изолированном Ubuntu после отказа для подменённого/обрезанного архива исходный DVT здоров, контрольные суммы настроек и ID контейнеров совпали. Подлинные .deb и все 10 OCI pins проверены на том же хосте. |
| `SAC-02` | `PASS` | На Ubuntu 24.04 без внешних маршрутов пустой daemon получил 10 OCI pins. Холодная установка завершилась по ID `45e8cada-9ee1-4ecd-ae78-766f7e8fe7b3`. Версия 1.25.0-rc1, ревизия 0070, расширение READY и wheel импортируется в Gateway и worker, профиль ai-mcp здоров. На раннем snapshot loopback TLS потребовал статический localhost в изолированном mount namespace. Финальный числовой probe прочитал штатный журнал живого Ubuntu-мастера через HTTPS при принудительно заблокированном socket resolver. Обновление завершилось по ID `047495e5-bbef-4503-8ac6-7467ca0143a4`, 1.25.0-rc1 → 1.25.0-rc2, ревизия 0070, ai-mcp и импорт wheel подтверждены. Из sealed copy по тому же ID восстановлен исходный 1.25.0-rc1/0070 в новый каталог и новый PostgreSQL. Подтверждены исходный админ, проект, расширение и граница данных. Восстановление использовало предварительно импортированные проверенные образы в том же отключённом namespace. |
| `SAC-03` | `PASS` | Тест закрепляет офлайн-операцию в общем `OperationStore.admit/claim`, проверяет отклонение конкурирующего запроса и владельца, а затем отказ без загрузки из сети при отсутствии архива. |

## 4. Проверки

| Команда/проверка | Результат | Детали |
| --- | --- | --- |
| DVT venv `python -m pytest -q tests/unit/scripts/offline tests/unit/services/installation_manager tests/unit/src/modules/extension_management --basetemp=tmp/pytest/stage08-current --tb=short` | `PASS` | Финальный снимок: 258 прошли, 6 Linux-only пропущены на Windows. |
| Distributor venv `python -m pytest -q tests/services/offline_download tests/services/dvt_distribution --tb=short` | `PASS` | 117 прошли, включая 4 новых теста. Песочница Windows блокировала временные каталоги pytest, повторный запуск был одобрен. |
| DVT venv, адресная перепроверка архива, совместимости executor, исключения кэша из копии и pip | `PASS` | 20 прошли. |
| DVT venv `python -m pytest -q tests/unit/services/installation_manager/test_candidate_probe.py tests/unit/services/installation_manager/test_candidate.py` | `PASS` | 11 прошли. Реальный TLS-сервер подтверждает работу при отключении socket resolver, SNI, Host и Bearer. Сертификат с неверным SAN отклонён до HTTP. |
| DVT venv `python -m pytest -q tests/unit/services/installation_manager/application/test_verified_staging.py` | `PASS` | 27 прошли, включая провал при конкурирующем допуске/владельце и отсутствие fallback из offline в Distributor/Registry. |
| Producer/consumer interop на Buildx OCI fixture | `PASS` | Реальный DVT verifier принял архив фактического сборщика Distributor. Ready и Registry transport подставлены локально, OCI manifest/config/layer взяты из Buildx. |
| Distributor frontend `npm.cmd run build -- --outDir ../../tmp/stage08-offline-frontend` | `PASS` | Vite собрал 28 модулей. Одобренный повтор после Windows sandbox realpath EPERM. |
| Distributor frontend, Node со stub fetch | `PASS` | Запросы DVT install/base и update/ai-mcp содержат ОС и её версию. Исходный запрос DCC update сохранён, отказ 409 доходит до UI из detail. |
| `bash -n` | `PASS` | Шесть изменённых sh-файлов DVT и seed_data/dvt; для Windows Git Bash нужен запуск вне sandbox. |
| DVT `audit_module.py src/modules/extension_management`, Ruff, `git diff --check` обеих репозиториев | `PASS` | Нет нарушений слоёв и ошибок lint/whitespace. |
| Ubuntu 24.04, изолированный net+mount namespace, Docker/containerd с отдельными пустыми roots | `PASS` для install и update | Update staging 36 с. В журнале последовательность PREPARED → BACKUP → MIGRATING → APPLYING → VERIFYING → RESUMING → SUCCEEDED. Ревизия 0070 сохранена по маршруту с неизменной схемой. |
| Ubuntu, полное восстановление из sealed copy | `PASS` | Копия `sha256:4ee1ffd52366f6ba09e6e480169234ce058e1a72da58cd9b2477a84865b2c51c`, cutoff `2026-11-16T17:58:44.821424+00:00`. Файл до cutoff сохранён, файл после cutoff отсутствует, gate возобновил admission после защищённой проверки. 48.469 с применение данных, 155.853 с с запуском и проверкой. Копия раннего тестового снимка содержит транспортный кэш, 2898255551 байт в data.tar.gz. Финальный код исключает этот кэш, что проверено отдельным тестом. |
| Ubuntu, финальный числовой TLS probe на живом мастере | `PASS` | `socket.getaddrinfo` принудительно заблокирован. Прочитаны текущий журнал, операция и claim через штатный CA и машинную авторизацию. |
| Provision чистого Linux хоста без Docker, реальная установка .deb | `NOT_RUN` | В изолированном контуре проверяли уже установленный Docker 29 containerd. Проверку APT-симуляции/установки следует проводить на чистом совместимом образе. |

## 5. Известные ограничения и риски

- Доставка доверенного host CLI, Python и wheelhouse происходит до установки. В [руководстве](../../../../scripts/offline/README.md) приведены подключённый сбор колёс и локальная установка с `--no-index`. Публикация продакшен-архива и полномасштабная проверка канала доставки относятся к следующей приёмке, производство не менялось.
- Заявленная матрица Linux amd64 использует containerd image store на Debian 13 или Ubuntu 24.04. Два варианта Compose profile: base и ai-mcp. Для .deb, которым нужны зависимости из базовой ОС, положите локальные пакеты в профиль до упаковки или подготовьте их на хосте.
- Профиль обновления сохраняет код существующего расширения, проверяя его по подписанному дереву. Можно добавить новые расширения и недостающие wheels. Смена кода существующего расширения и активная очередь удалений требуют отдельного перехода.
- На управляемом экземпляре CLI подтверждает, что закреплённый локальный executor понимает офлайн-комплект. Особый bootstrap проходит совместимый legacy adoption с готовым executor по digest. Применение использует локальный HTTPS мастера. Внешний Distributor, Registry, DNS и публичный TLS в применении не участвуют. Время работы, первой активации, простоя и восстановления измеряется в сквозном AT-12.

## 6. Вопросы мастер-агенту

Нет.

## 7. Артефакты

- [producer_reader_interop.txt](artifacts/producer_reader_interop.txt) фиксирует принятые SHA-256 на межрепозиторной проверке.
- Результаты VM фиксирует мастер-агент. Большие пакеты, приватные ключи и сырые логи в каталоге этапа отсутствуют.

## 8. Итерации исправлений

Пока нет.
