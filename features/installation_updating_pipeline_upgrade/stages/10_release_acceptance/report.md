# Отчёт об этапе 10. Release gate, документация и приёмка

- **Статус:** `PARTIAL`
- **Задание:** [task.md](task.md)
- **Режим:** `FIX`

## 1. Что сделано

- Linux amd64 release Bake сохраняет фиксированный путь `services/ui`.
  Генератор берёт backend SHA и UI gitlink из исходного Git, затем связывает
  BuildKit leaf digest, PostgreSQL, Valkey, Compose, самодостаточный bootstrap,
  совместимость и ревизию миграций в одном подписанном манифесте. Gateway и
  migrate имеют один descriptor. Skopeo считывает слои и измеряет консервативный
  бюджет байтов и inode. Первый запуск блокируется на упаковке, если минимум
  preparer выше версии executor, в том числе при сравнении RC со stable.
  При обновлении можно передать предшествующие точные leaf PostgreSQL и
  Valkey через `DVT_RELEASE_INFRA_REFS_FILE`.
- CI проверяет integration lock против манифеста, передаёт SHA-256 точного
  конверта в защищённую job приёмки и требует AT-01 на обеих ОС и все другие
  AT в совокупности. Для восстановления учитывается отдельный получатель.
  После receipt использует копирование Registry по digest и вызов рабочего
  Distributor. Подтверждение клиента появляется после условной записи S3.
- Приватный Distributor отдаёт кандидаты через тот же read API. Издатель
  сверяет Git SHA и gitlink, точные байты bootstrap и семантику Compose,
  проверяет все клиентские образы и подписанный receipt. Команда
  `--dry-run` проверяет эти условия без S3-клиента.
- Поставка bootstrap для каталога использует один утверждённый manager digest
  как bootstrap и executor. Дополнительная CA сохраняется при создании
  host identity. Для явного отдельного manager-handoff target действует
  требование distinct digest.
- Добавлены руководство оператора, CI runbook и воспроизводимая матрица
  стенда с методикой замеров.

## 2. Изменённые файлы

| Путь | Изменение |
| --- | --- |
| `dvt/docker/docker-bake.release.hcl` | Платформа целей релиза и проверка формата RC. |
| `dvt/scripts/release/{build_manifest,image_inventory,acceptance}.py` | Инвентаризация образов, упаковка и подпись, evidence/receipt. |
| `dvt/scripts/release/capture_vm.sh` | Сбор безопасных фактов ВМ без выгрузки окружения. |
| `dvt/services/installation_manager/host_bootstrap.py` | Один управляемый стартовый digest и CA до старта. |
| `dvt/services/installation_manager/infrastructure/{staging_compose,staging_docker}.py`, `dvt/tests/unit/services/installation_manager/application/test_verified_staging.py` | Раннее обнаружение занятых имён контейнеров из подписанного Compose и регрессии staging. |
| `dvt/services/proxy/Caddyfile`, `dvt/tests/unit/services/proxy/test_caddyfile.py` | Отдельный обработчик 404 для выключенного AI MCP. |
| `dvt/README.md`, `dvt/docs/README.ru.md`, `dvt/services/installation_manager/{bootstrap_candidate,customer_installation,operator_browser,release_catalog}.md` | Установка, защищённый URL, сценарий UI, CLI, диагностика и ссылки на восстановление. |
| `dvt/tests/unit/scripts/release/test_release.py`, `dvt/AGENTS_CHANGELOGS.md` | Проверки упаковки и матрицы, запись helper. |
| `dvt_cicd/.gitlab-ci.yml`, `dvt_cicd/.ci/gitlab/jobs/{02-build-test,04-release-flow}.yml` | Связь кандидатов, интеграции, защищённой приёмки и публикации. |
| `dvt_cicd/scripts/ci/internal/{promote_dvt_release,publish_dvt_assets}.py` | Копирование по digest и upload неизменяемых файлов. |
| `dvt_cicd/tests/unit/ci/{test_gitlab_configuration,test_dvt_release_promotion}.py`, `dvt_cicd/docs/{DVT_RELEASE_GATE,DVT_CI_CD_GUIDE}.md` | Проверки отказов и последовательность переключения проектов. |
| `denvic-distributor/services/dvt_distribution/releases/{candidate,manifest,publish,router,store}.py` | Приватный каталог, общий read API, проверка клиентских файлов и сухой режим. |
| `denvic-distributor/services/dvt_distribution/README.md`, `denvic-distributor/tests/services/dvt_distribution/test_dvt_releases.py` | Команды и тесты выбора, доставки и readiness. |

## 3. Критерии приёмки

| Критерий | Статус | Подтверждение |
| --- | --- | --- |
| SAC-01 | `NOT_RUN` | Изолированная доставка и базовый браузерный прогон на исправленном Ubuntu-кандидате прошли. Полное покрытие AT-01–AT-13 остаётся открытым. |
| SAC-02 | `NOT_RUN` | Локальные dry runs, тестовые отказы и условная запись адаптера прошли. Реальная завершающая protected job с Registry/S3 writer и запись готовности требуют полного VM receipt. |
| SAC-03 | `NOT_RUN` | Руководства и методика готовы. Пороговые значения времени и полные серии замеров на обеих ОС ожидают стендовой приёмки. |

## 4. Проверки

| Команда или проверка | Результат | Детали |
| --- | --- | --- |
| `docker buildx bake -f docker/docker-compose.base.yaml -f docker/docker-compose.dev.yaml -f docker/docker-compose.prod.override.yaml -f docker/docker-bake.release.hcl release --print` | `PASS` | Все восемь целей amd64, UI из `services/ui` даже при внешнем `UI_BUILD_CONTEXT`. |
| `docker compose --profile '*' -f <generated-compose> config --images` | `PASS` | Синтетический Compose: 11 ролей, Gateway=migrate, без mutable refs. |
| PyYAML parser с `!reference` и Git Bash `bash -n` | `PASS` | Локальный синтаксис GitLab jobs и `capture_vm.sh`. |
| DVT venv `python -m pytest -q tests/unit/scripts/release/test_release.py tests/unit/services/installation_manager/test_candidate.py` | `PASS` | 21 прошёл. |
| DVT venv `python -m ruff check scripts/release services/installation_manager/host_bootstrap.py tests/unit/scripts/release/test_release.py` | `PASS` | Проверены изменённые Python-файлы DVT. |
| DVT venv `python -m pytest -q tests/unit/services/installation_manager/infrastructure/test_offline_bundle.py tests/unit/services/installation_manager/application/test_release_catalog.py` | `PASS` | 19 прошли. |
| Distributor venv `python -m pytest -q tests/services/dvt_distribution/test_dvt_releases.py` | `PASS` | 12 прошли, включая dry run, source mismatch и условную запись объекта. |
| Distributor venv `python -m pytest -q tests/services/offline_download/test_dvt_bundle.py` | `PASS` | 4 прошли. |
| CICD venv `python -m pytest -q tests/unit/ci/test_dvt_release_promotion.py tests/unit/ci/test_gitlab_configuration.py` | `PASS` | 13 прошли, включая ненулевой выход при сбое promotion, неполноте и подмене. |
| Изолированная проверка `publish_dvt_assets` в Distributor venv | `PASS` | Два digest-объекта записаны через условный интерфейс. Подмена локальных bytes отклонена до отправки. |
| DVT venv `python -m alembic heads` | `PASS` | `0070 (head)`. |
| `git diff --check` по изменённым tracked файлам | `PASS` | В трёх проектах, предупреждения Git о LF/CRLF. |
| CI runner и внешний GitLab lint | `NOT_RUN` | Проверены локальная структура, нужные зависимости job и синтаксис shell. |

### Стендовый снимок

Мастер подтвердил сборку восьми образов из точных архивов backend
`7fe257b129adb329faea503e2e17af6eaf4d2be9` и UI
`543b246ce6abf673fc4a41943365f5d853650377`. Приватный TLS Registry подтвердил
байты всех восьми leaf. Skopeo на Ubuntu прочитал и измерил 11 ролей.
Изолированный Distributor вернул по HTTPS exact manifest для кандидата
`1.24.0-rc2` с digest
`sha256:77b0413adaff153a0dad08e3a3d66a6902adb3c985cd9e4a9fe078e951366ce4`
и стендового источника `1.23.99` с digest
`sha256:466006d2ef5affd2e5a03469c50f86e56d749d4369ae63c2ae06ee255627a6ed`.
Ubuntu и Debian подготовлены с независимым Docker/containerd и пустым кэшем.
Этот артефакт bootstrap относится к базовому `7fe257b`.

На Ubuntu холодный запуск хостового bootstrap занял 11 с, на Debian — 69 с.
Chromium на обеих ВМ подтвердил RC. После потери ответа HTTP 202 сохранился
ровно один operation ID. Executor остановил применение с
`incompatible_release` до изменения стека, потому что тестовый подписанный
порог `minimum_preparer_version=1.24.0` превышал версию образа
`1.24.0rc2`. Это ожидаемый отказ проверки версии. Загрузку Docker на
чистую ОС и время до первого входа эти два замера ещё не подтверждают.

| AT | Статус | Что требуется для подтверждения |
| --- | --- | --- |
| AT-01 | `NOT_RUN` | Базовый браузерный прогон Ubuntu и первый вход прошли. Установка Docker с нуля подтверждена отдельными APT-пробами на обеих ОС. Остаётся связать шаги в полном проходе на каждой ОС, в том числе повтор и отказ при конфликте. |
| AT-02 | `NOT_RUN` | На стенде источник остался доступен во время повторной попытки с MTU 1280. Остальная матрица сетевых отказов и зависший Compose остаются открытыми. |
| AT-03 | `NOT_RUN` | Дефицит ресурсов на ФС с сохранением готовности источника. |
| AT-04 | `NOT_RUN` | Ubuntu сохранила ту же операцию после восстановления отсутствовавшего мастера. Остались сценарии замены в полном Compose, Created и ошибка старта новой версии. |
| AT-05 | `NOT_RUN` | На исправленном Ubuntu-кандидате потеря 202 после отменённой строки привела к выбору единственного нового ID. Подготовка продолжилась после восстановления мастера. В Debian браузер и CLI наблюдали один ID. Две вкладки с одной авторизацией и полная матрица перезапусков остаются открытыми. |
| AT-06 | `NOT_RUN` | На Debian прошёл актуальный переход 1.24.0-rc2 → 1.24.1-rc1 с проверкой проекта, аккаунта, ETL и MCP. Исторические регрессии и полный набор проверок остаются открытыми. |
| AT-07 | `NOT_RUN` | На Debian подтверждены дочерний NODE в RUNNING при закрытии, отказ нового запуска HTTP 503, пропуск cron, WORKER_LOST и единственный побочный эффект. Полная комбинация дочерней цепочки, длинной задачи и повторов ещё требует приёмки. |
| AT-08 | `NOT_RUN` | Точки отказа миграции, расширения и Gateway. |
| AT-09 | `NOT_RUN` | Debian → Ubuntu: на том же ID восстановлены данные, подтверждены аккаунт, проект, ETL и MCP. Проверено отклонение понижения с той же ревизией. Сценарии с установленным расширением в копии и несовместимой ревизией остаются открытыми. |
| AT-10 | `NOT_RUN` | На Debian подтверждён штатный включённый MCP. Путь с пустым env мастера при сохранённом секрете ожидает отдельной проверки. |
| AT-11 | `NOT_RUN` | Клиентский набор: подмена, RC, cache, offline каталог. Доставка exact HTTPS pins проверена отдельно. |
| AT-12 | `NOT_RUN` | Ubuntu установила точный подписанный архив без маршрута после устранения конфликта имён. Установка использовала существующий Docker cache. Стендовое offline-обновление и полное покрытие остаются открытыми. |
| AT-13 | `NOT_RUN` | На исправленном Ubuntu-кандидате прошли отдельная привязка setup, replay, первый вход и диагностика. Полное покрытие проверок доступа и истечения привязки остаётся открытым. |

## 5. Известные ограничения

- Версия проверяемого baseline совпадает с именем исторического RC. Для
  официального выпуска потребуется новый разрешённый Git-тег, версия source,
  утверждённая политика и полный receipt этого нового exact manifest.
- Права на writer, неизменяемая политика bucket и Registry, CI окружения и
  доверие настроены контрактом и руководством. Аттестация этих параметров в
  производственной инфраструктуре остаётся отдельным согласованным действием.
- Прежние тесты и синтетические fixtures дополняют live VM evidence. Профили
  без полного набора результатов и времени остаются вне заявленной поддержки.

## 6. Вопросы мастер-агенту

Какие дополнительные факты реальных ВМ следует внести после завершения независимого
прогона и подтверждения точных bytes каждого кандидата.

## 7. Артефакты

- [Проверки и сухие отказы](artifacts/local_checks.md)
- [Сценарии ВМ и форма доказательств](acceptance_matrix.md)
- [Воспроизводимая проверка маршрутов Caddy](artifacts/check_proxy_mcp.py)

## 8. Итерации исправлений

### Итерация 1 — 17 ноября 2026

**Стендовые отказы и ревью.** На Ubuntu 24.04, Compose 5.7.1 и Engine 29.10.0
на baseline-манифесте
`sha256:3befb0aeb9c55eec995fa192e218b7da210c9d842457006ec731f34ce523ab8f`
потеря bootstrap-контейнера привела к `prepared` без source digest.
Применение вернуло `manager_unavailable`, а после возвращения мастера
с тем же утверждённым образом — `incompatible_release`. Gateway, БД и
миграции ещё отсутствовали. После отмены операции новый POST с потерянным
202 на обеих ВМ создал новый ID, но Chromium оставил открытой отменённую
строку. Строгая проверка доставки в предыдущем release job выполнялась
после попытки записи тегов. [Замечания](fix_task.md)

**Исправления.** Онлайн INSTALL остаётся `preparing` с retryable
`manager_unavailable`, когда подтверждённый стартовый мастер отсутствует
до или после скачивания. При повторном host resume для того же ID на
`admitted/preparing` и пустом Compose-проекте восстанавливается только
образ из закрытого `current-manager`, проверенный по разрешённым digest.
Применённая поставка, занятый проект, offline и update исключены из
этого восстановления. После восстановления проверенный manager digest
попадает в `plan.json`, готовность подготовки сохраняется по прежнему ID.
UI воспроизводит точный POST с прежним Idempotency-Key и сверяет вид и
digest ответа, включая терминальную операцию. Открытие истории без
ожидающего намерения сохраняет выбранную строку. Release job проводит
подписанный Distributor dry run до version tags и legacy latest, затем
повторяет проверку доставки перед условным S3 commit.

**Файлы итерации.** `host_bootstrap.py`, `application/verified_staging.py`,
`infrastructure/staging_compose.py`, `frontend/src/{CandidateApp.jsx,candidateApi.js}`,
`frontend/tests/candidateAdmission.test.js`, `recovery.md`,
`tests/unit/services/installation_manager/{test_candidate.py,application/test_verified_staging.py}`,
`dvt_cicd/.ci/gitlab/jobs/04-release-flow.yml`,
`dvt_cicd/tests/unit/ci/{test_dvt_release_promotion.py,test_gitlab_configuration.py}`,
`dvt_cicd/docs/DVT_RELEASE_GATE.md`, `AGENTS_CHANGELOGS.md`.

| Проверка итерации | Результат | Наблюдение |
| --- | --- | --- |
| DVT venv `pytest` для release, candidate, verified_staging, offline_bundle, release_catalog | `PASS` | 81 тест. Внутри Windows sandbox старый тест resolve каталога не смог прочитать путь, одобренный локальный повтор прошёл целиком. |
| DVT venv Ruff по изменённым Python | `PASS` | Проверены runtime staging, bootstrap, release scripts и адресные тесты. |
| `node --test tests/candidateAdmission.test.js` | `PASS` | Четыре теста, в том числе потеря 202 после отменённой строки для preparing и succeeded, защита kind/digest и просмотр истории. |
| `npm run build` в installation_manager/frontend | `PASS` | 39 модулей Vite, одобренная локальная сборка после sandbox realpath. |
| CICD venv `pytest` для promotion/config | `PASS` | 14 тестов. Реальный shell-блок job с тестовыми командами вернул 23 при отказе dry run. Ни Registry writer, ни ready writer не вызваны. |
| Адресный повтор Chromium/host resume на Ubuntu | `PASS` | Исправленный master и подписанный конверт указаны в итерации 2. Выбор нового ID после отмены и восстановление того же ID подтверждены. |
| Адресный повтор Chromium/host resume на Debian | `NOT_RUN` | Нет результата на исправленном master и bootstrap. |

**Точный комплект для повторной проверки.** Для приватного стенда взять
source `7fe257b129adb329faea503e2e17af6eaf4d2be9` с UI gitlink
`543b246ce6abf673fc4a41943365f5d853650377` и пересобрать цель
`installation_manager` с runtime-файлами исправлений ниже. Для bootstrap и
executor использовать этот же новый Linux amd64 leaf. Новый manifest
содержит этот leaf у `installation_manager`, прежние семь продуктовых
образов и два образа инфраструктуры из pin inventory, общий Gateway digest
для `migrate` и
новые точные bytes `host_bootstrap.py` в роли bootstrap asset. Для
сценария замены с различными ролями использовать отдельно проверенный
source или target manager digest. Подпись и delivery подготовить в новом
изолированном каталоге RC. Для официального выпуска требуется отдельная
проверка Git-тега с неизменённым тегированным содержимым.

| Файл DVT | SHA-256 байтов рабочей копии для повторной сборки |
| --- | --- |
| `services/installation_manager/host_bootstrap.py` | `8c0081ed1e3a3638d0f8099c22955551788d6a6875565b03058064cc7a5dfa3b` |
| `services/installation_manager/application/verified_staging.py` | `f8fd642f42ef3638897e17d881dd93178f1e4fc765f4cd27e2b5fcffdb43c5b6` |
| `services/installation_manager/infrastructure/staging_compose.py` | `d89f64875ea20fb2ab94ef846fa7d5d7a693d0d02aef46726fee8e4c06900bca` |
| `services/installation_manager/frontend/src/CandidateApp.jsx` | `b89e214cb231c2262ce9889b0098aaef228a0077d916c8fba371d37939e6e0ec` |
| `services/installation_manager/frontend/src/candidateApi.js` | `f6e1a10c32f7f7bd68175b4471b5a4156d6e1a0e8530f10b3c3f32ebf9ad1781` |

Снять manager до первого запуска detached executor новой операции;
повторный bootstrap должен вернуть подтверждённый образ и тот же ID.
Отдельно потерять ответ 202 новой операции, пока браузер показывает
отменённый ID, и подтвердить автоматический выбор нового ID, журнальную
стадию и отсутствие второго допуска. Включить вариант быстрого завершения.

### Итерация 2 — 17 ноября 2026

**Фактическое наблюдение.** Ubuntu 24.04, Engine 29.10.0, Compose 5.7.1.
Исправленный master
`sha256:60d9dc979cdc8eeef4461af1f0d62a67508dc792a2f074c870c87c2f8b168006`,
подписанный стендовый manifest
`sha256:323d428f8de585dec0ab6171f1f3a9a2e3beaacf46a0e6645069f5f233b62f97`.
Chromium после потери 202 выбрал один новый ID
`59bb593a-ac4f-480f-82f2-79fda31c28a7` при ранее выбранной отменённой операции.
При снятии мастера подготовка остановилась в `preparing` с
`manager_unavailable`; `plan.json` отсутствовал. Хостовый `resume` вернул
закреплённый образ и тот же ID. Мигратор завершился кодом 0 на ревизии
`0070`, Gateway, UI, Worker и Scheduler подтвердили готовность.
Базовая операция осталась в `verifying`: старый Proxy при выключенном
AI MCP отдал на `GET /mcp` ответ UI `200 text/html`. [Замечание](fix_task.md)

На Debian с предыдущим кандидатом и включённым AI MCP подтверждены повтор
bootstrap, вход первого администратора, контрольный ETL, вызов MCP и RBAC.
Отдельная APT-проба без Docker установила Engine 29.10.0 и Compose 5.7.1 за
14,801 с; оба прежних стендовых стека были сохранены и отвечали HTTP 200.
Эти замеры подтверждают отдельные шаги. Нового полного прохода первого
установочного пути с чистой ОС и последующим входом в этом прогоне нет.

**Исправление.** `services/proxy/Caddyfile` возвращает `404` внутри
`handle @mcp_disabled`. Он участвует в одной группе взаимоисключающих
обработчиков с MCP, API и UI. Условия выключенного и включённого профиля
взаимно исключаются. Readiness сохраняет требование 404. SHA-256 байтов
исправленного Caddyfile
`fbf9f59be51fa5d4d3a22d28fb0176492d88d4081fe0c8e5745bda1db95af9a5`.

| Проверка итерации | Результат | Наблюдение |
| --- | --- | --- |
| Caddy v2.8.4 с baseline Caddyfile `7fe257b` | `FAIL` | Воспроизведены 200 от UI для GET /mcp и POST /mcp/configured при unset и false. Fixture завершился 1. |
| Тот же Caddy с исправленным Caddyfile | `PASS` | Unset и false дают 404 для обеих форм пути. При true MCP upstream получил исходные методы и пути, fixture upstream ответил 202. /mcp-example, /workspace и /api/health сохранили ожидаемые upstream и 200. |
| DVT venv `pytest -q tests/unit/services/proxy/test_caddyfile.py` | `PASS` | 1 тест. |
| DVT venv Ruff и `git diff --check` для файлов итерации | `PASS` | Санитизированный fixture и unit-тест. |
| Ubuntu base profile с новым подписанным Proxy leaf | `PASS` | Отдельный подписанный кандидат прошёл базовый браузерный сценарий, ревизия 0070, GET и POST к MCP возвращают 404. |

**Повтор на ВМ.** Ubuntu 24.04 прошла отдельную базовую установку
с выключенным AI MCP на новом подписанном комплекте. Linux amd64 Proxy
`sha256:77b642aedca4d243086965f5f0809295fe4d41ee2aabfe1dcf30e3e8528337b8`,
master `sha256:60d9dc979cdc8eeef4461af1f0d62a67508dc792a2f074c870c87c2f8b168006`,
манифест `sha256:8d04000880b710a58dbb51f90b878883e3974f1a252465d6a8ee4981086bbd48`.
Браузерный цикл операции `b4dea05f-2254-4e3f-843a-bf6d483c0849` занял
78,073 с. Схема достигла `0070`, `GET /mcp` и `POST /mcp/probe` вернули
`404`. Отдельная привязка setup, повтор запроса, первый вход и диагностика
прошли. У предыдущей операции в `verifying` сохранены исходные pin,
Compose и план.

В отдельном эксперименте на Ubuntu подкоманда подписанного
bootstrap прошла APT-установку на хосте без Docker за 43,400 с. После
эксперимента оба изолированных стека восстановлены и ответили HTTP 200.
Это самостоятельный замер, а браузерный цикл измерялся отдельно.

Локальный тест использует уже загруженный бинарник Caddy, отдельные
фиктивные upstream и контейнер без внешней сети. Запуск из корня DVT
с уже загруженным локальным Proxy:

~~~powershell
$env:PYTHONPATH = (Get-Location).Path
.venv/Scripts/python.exe features/installation_updating_pipeline_upgrade/stages/10_release_acceptance/artifacts/check_proxy_mcp.py --image dvt-acceptance.invalid/dvt/proxy:stage10-7fe257b
~~~

Для воспроизведения отказа добавьте
`--source-revision 7fe257b129adb329faea503e2e17af6eaf4d2be9`.
[Воспроизводимый скрипт](artifacts/check_proxy_mcp.py)



### Итерация 3 — 17 ноября 2026

**Стендовый факт.** На Debian прошёл защищённый переход
`1.24.0-rc2 → 1.24.1-rc1` на схеме `0070`. Сохранились исходные
проект и аккаунт, контрольный ETL и project-scoped MCP вернули ожидаемый
результат. Для отдельного восстановления на Ubuntu использована точка
операции `939f34cd-26f0-4cea-a432-1f474f0f9dbc` с манифестом копии
`sha256:33bcbd6987ffde087353380011d2a580427a4b679c2b4f740658dea2cec4bb7c`.
Граница данных `2026-11-17T06:43:38.519909+00:00`. PostgreSQL и
постоянные файлы восстановлены в отсутствовавший канонический каталог за
4,014 с, gate оставался frozen. Файл после границы отсутствовал. Запуск
остановился с `recovering/compose` до создания контейнеров.
Gateway в сохранённом Compose уже содержал два защитных read-only bind и
дополнительную сеть мастера. Проверка сравнивала его целиком с исходным
мигратором. [Замечание](fix_task.md)

**Исправление.** `application/restore_runtime.py` распознаёт только
известный wiring сохранённого Gateway. Проверяются точные source/target
CA и токена, флаги read-only и `create_host_path=false`, локальные защищённые
файлы и каноническая сеть мастера `<project>_default`. Для сравнения с
мигратором создаётся временное представление Gateway без проверенной пары
и дополнительной сети. Compose, передаваемый Docker, сохраняет исходный
wiring. Общий валидатор приложения, условия получения функционального
доказательства и открытие gate сохранены.

| Проверка итерации | Результат | Наблюдение |
| --- | --- | --- |
| DVT venv `pytest -q` для `test_restore_runtime.py`, `test_portable_restore.py`, `test_application_apply.py`, `test_offline_bundle.py` | `PASS` | 37 тестов. Регрессия проверяет подписанный release pin, защищённые файлы, архив и журнал на диске. Корректный сохранённый Compose и прежний `RECOVERING` ID доходят до `VERIFYING`, с тем же Gateway wiring. Старый Compose без wiring также проходит. |
| Отрицательные варианты сохранённого Compose | `PASS` | Неполная пара, подменённый/пропавший source, writable и create-host-path bind, лишний bind или сеть, подменённое имя default и добавление bind к мигратору блокируют запуск до Compose up. |
| Ruff и `git diff --check` | `PASS` | Проверены изменённые Python-файлы. |
| Продолжение той же копии на Ubuntu с исправленным runtime | `PASS` | Исходный ID восстановлен, gate открыт после функционального подтверждения. В этой копии установленный набор расширений пуст. Подробности ниже. |

**Минимум для повторной проверки.** Единственный runtime-файл правки
`services/installation_manager/application/restore_runtime.py`
(SHA-256 `582d70f3e1ef426169e670ab166dd7a7a018d9a3c2ac2b71fa1b282ac1506115`).
Для точечного стенда использовать этот файл в существующем host checkout
и DVT venv на Ubuntu, затем повторить
`python -m services.installation_manager.application.restore_runtime start`
с тем же `--dir` и `--operation-id 939f34cd-26f0-4cea-a432-1f474f0f9dbc`.
Восстановленный каталог, готовая копия, авторизация и закреплённые образы
остаются источниками этой операции. После `VERIFYING` пройти штатный
`finalize` со свежей административной сессией и сохранённым проектом.
Открытие gate должно последовать после подтверждённого функционального
доказательства.

**Функциональная проверка при закрытом gate.** Первый повтор после правки
Compose достиг `verifying` на исходных образах. Вход и GET `/api/user/info`
вернули 200. Обычные GET проекта и расширений ответили
`503 SYSTEM_UPDATING` через Proxy и loopback, из-за чего прежний
`finalize` остановился в `verifying/gateway_unavailable`.

Проверка подтверждает административную сессию живым
`GET /api/user/info`. Затем в точном локальном Gateway одноразовый
процесс запускает в памяти штатные GET-обработчики проекта и расширений
с той же cookie. Используются исходные зависимости аутентификации и
прав доступа, сетевой слушатель отсутствует. Установленные записи
сверяются с фактическим списком той же восстановленной БД.
Readiness, публичная блокировка и последовательность открытия gate
сохраняются. Полный overlay обеих правок состоит из того же
`services/installation_manager/application/restore_runtime.py`
с SHA-256 `f39e0a210714f8aa476f9fcb950b770d244a9ff92de3c03f2599e857fa906feb`.

| Проверка функционального подтверждения | Результат | Наблюдение |
| --- | --- | --- |
| DVT venv `pytest -q` по restore, portable restore, apply, offline bundle и `services/gateway/update_runtime/test_middleware.py` | `PASS` | 55 тестов. Реальный middleware fixture оставляет публичные GET закрытыми. Локальный сценарий отклоняет неверную cookie, UUID и несовпадающий список расширений. |
| Ubuntu retry с полным overlay и тем же ID | `PASS` | `939f34cd-26f0-4cea-a432-1f474f0f9dbc`. Неверная cookie и валидная cookie с неверным UUID отклонены. До корректного подтверждения публичный проект оставался 503. |
| Функциональный результат Ubuntu после открытия gate | `PASS` | Исходный `1.24.0-rc2` по pin `sha256:3befb0aeb9c55eec995fa192e218b7da210c9d842457006ec731f34ce523ab8f`. Новый PostgreSQL identity, файл после границы отсутствует, прежние аккаунт и проект доступны. Повторно проверен пустой установленный набор расширений. Реальный Worker ETL `SUCCESS`, MCP `list_projects` через Proxy прошёл. |
| Debian downgrade через авторизованный Chromium | `PASS` | `1.24.1-rc1/0070 → 1.24.0-rc2/0070` отклонён HTTP 422 `incompatible_release` за 3,706 с, исходный стек и журнал сохранились. Это проверка запрета понижения с той же ревизией. |

Замер физического восстановления данных составил 4,014 с. Повтор запуска
и функциональной проверки занял 73,835 с, включая отрицательные попытки и
проверку публичных чтений после открытия gate. Это два отдельных замера.
Копия не содержала установленных расширений. Полное покрытие AT-09 и
матрицы остаётся открытым.


### Итерация 4 — 17 ноября 2026

На отдельной offline-установке Ubuntu операция
`a00b91e6-551f-4623-b787-2a8d35b538e8` с подписанным pin
`sha256:3befb0aeb9c55eec995fa192e218b7da210c9d842457006ec731f34ce523ab8f`
застряла в `migrating/database_unavailable` до создания PostgreSQL.
Подписанный Compose задавал `container_name: dvt-postgres`. Имя занимал
остановленный контейнер другого проекта на общем Docker Engine. Прежняя
проверка наблюдала только контейнеры целевого проекта.

Подготовка теперь проверяет явные имена активных сервисов глобально,
включая остановленные контейнеры. Для занятого имени должны совпасть
метки проекта и роли. Контейнеры одноразовых запусков блокируют подготовку.
Отказ до сохранения плана остаётся в `preparing` с причиной `compose`.
Сообщение содержит имя и роль целевого Compose. Контейнер совпавшей роли
проходит обычную проверку исходного образа, mount и сети. Список явно
заданных имён берётся из подписанного Compose после разрешения активных
профилей.

| Проверка | Результат | Наблюдение |
| --- | --- | --- |
| DVT venv, staging, offline bundle, apply и restore | `PASS` | 83 теста, 4 пропущены. Подписанный staging с чужим остановленным контейнером, одноимённой ролью с неверной меткой и one-off блокируется до pull и плана. После устранения конфликта сохраняются ID и pin. Собственная роль по-прежнему проверяет исходный digest. |
| Локальный Docker Engine 29.1.3 | `PASS` | Два точных повторных фильтра `name` вернули оба остановленных контейнера с дефисами в именах. Соседнее имя с суффиксом исключено. Запрос по метке целевого проекта пуст. Диагностика не содержит ID, меток или env другого контейнера. |
| Независимый Debian, Docker Engine 29.10.0 | `PASS` | На двух точных runtime-файлах сработали два повторных фильтра. Собственный подписанный Compose прошёл. Чужой остановленный контейнер отклонён до плана. Указатель релиза и HTTP 200 исходного стека сохранились. |
| Ubuntu, повтор той же offline-установки | `PASS` | После временного освобождения имён собственных стендовых контейнеров тот же ID достиг `succeeded`, PostgreSQL 0070, профиль AI MCP и HTTP 200. Installer, executor и Engine были в одном сетевом namespace без маршрута, использовался локальный Docker cache. Исходный стенд восстановлен со своими именами и HTTP 200. |

Для точечной проверки preflight оба файла должны одновременно
соответствовать рабочей копии этапа:

- `services/installation_manager/infrastructure/staging_compose.py`
  SHA-256 `40691b7108eecc4d7e35875415a4a3884b86f63ce599d671270a22b71d52f14b`.
- `services/installation_manager/infrastructure/staging_docker.py`
  SHA-256 `85199c06ac33ce9a19e52919021dd2d75a727f6d9208b1f04eb3091c09e2fae0`.

В продуктовой сборке оба файла входят в `installation_manager`. После
пересборки его digest должен быть согласован с bootstrap, манифестом и
доказательствами приёмки. Повтор Ubuntu выше подтверждает пригодность
подписанного offline-архива после устранения конфликта. Отказ новой
проверки на реальном Docker подтверждён отдельным прогоном Debian.

На Debian операция `c2728251-bef6-4acb-a6cb-b4459f1f98f5` для
`1.24.1-rc2` с pin
`sha256:6a23c08c295529a8f7da92bb334bcf6c57229e84863830ef42211a82b4dd47f9`
показала один ID в браузере и CLI. При блокировке дочерняя NODE оставалась
`RUNNING`, новый независимый запуск получил 503, cron пропущен за полный
минутный интервал. После остановки worker зафиксированы
`ERROR/WORKER_LOST`, одна task и одна строка побочного эффекта. Тот же ID
дошёл до `succeeded`, прежний вход и HTTP 200 сохранились, тестовое
расписание удалено. Повтор с одним idempotency key в двух вкладках этим
прогоном не подтверждён, поскольку отдельные входы того же аккаунта
отозвали предшествующую сессию.


### Итерация 5 — публичная команда без системного Python

Зафиксирован исходный отказ на Debian 13. Публичный raw URL отдавал прежний
`install.sh` из GitHub DVT `main`. Он запускал HTTP-мастер по mutable
`installation_manager:latest`, а `/api/operations/active` отвечал 404.
У публичного Distributor `/health` отвечал 200, маршрут каталога — 404.
Публичная выдача и действующие инсталляции в ходе исправления не менялись.

- Сохранены URL и команда
  `bash <(sudo curl -fsSL https://raw.distribution.denvic.tech/dvt/install.sh)`.
  Новый файл написан на POSIX sh. Через TLS он запрашивает дескриптор
  для ОС и платформы, ограничивает объём файлов и сверяет размер и SHA-256
  bootstrap до повышения прав и согласованной подготовки Docker. При отказе
  каталога, TLS, ошибке формата или подмене новый хост не меняется, переход
  на HTTP отсутствует.
- Distributor добавляет `GET /api/v1/dvt/releases/install` к существующему
  проверяющему reader. Публичный результат — самый новый готовый stable с
  поддержкой чистой установки данной ОС. Для частной приёмки RC требуется
  явный выбор. Launcher запрашивает `application/vnd.dvt.install+json`,
  проверяет строгие заголовки `X-DVT-*` и хеш policy JSON. JSON разбирает
  подписанный bootstrap внутри закреплённого образа. Обычный JSON-ответ
  остаётся для ручной проверки дескриптора.
- `bootstrap.py` остаётся прежним по формату артефактом релиза. Изменённый
  bootstrap работает в одноразовом контейнере по закреплённому digest с
  Docker socket, каталогом выбранного экземпляра, host os-release и
  read-only backing paths. Корень хоста не монтируется. `--privileged`,
  `--pid=host` и отдельный постоянный контейнер не используются. Python
  и генерация TLS выполняются внутри образа, хост готовит Docker и systemd.
  Подтверждение Docker APT остаётся отдельным. На хосте Python не требуется.
- Сохранённый root-owned `.bootstrap/host-launch.sh` сверяет digest
  локального bootstrap. Повтор и systemd используют прежние TLS, identity,
  manager и активный ID без запроса нового release. При отсутствии
  активного ID и контейнера мастер запускается из last-known digest.
  Тот же shim обслуживает `recover-manager`, `restore-start` и команды
  обслуживания. На рабочее место по проверенному SSH переносится только
  публичная CA, fingerprint показывается установщиком. Публичный адрес
  приложения и loopback URL мастера настраиваются отдельно.
- Прежний мастер доступен через существующий явный raw путь
  `dvt/services/installation_manager/install.sh`. Путь и Compose включены
  в пример allowlist. Ручной и offline-маршруты с хостовым bootstrap
  сохраняют свои команды. [Руководство оператора](../../../../services/installation_manager/customer_installation.md)

| Проверка | Результат | Наблюдение |
| --- | --- | --- |
| Изолированный Debian 13, `network=none`, `/bin/dash -n` и `--help` | `PASS` | В тестовой среде нет `/usr/bin/python3`. Хостовый launcher и сохранённый shim работают через shell. Python тестовой venv имитирует вход в точный временный образ. |
| Две регрессии Debian с реальным OpenSSL, HTTPS и Bash process substitution | `PASS` | Docker CLI и systemd — стендовые адаптеры. Положительный сценарий проверил получение policy, pinned manager, выпуск и проверку localhost TLS, побайтную сохранность ключей, identity и pins, тот же ID при повторе и в shim без controlling TTY. При пустом журнале восстановился точный last-known manager. Отказы включают 404, 503, TLS, перенаправление, повреждённые bytes, неполный дескриптор и подмену сохранённого bootstrap. |
| Независимый Ubuntu 24.04 без Python | `PASS` | Одноразовый контейнер без внешней сети, Docker, curl, sudo и systemctl — тестовые адаптеры. Проверены прежняя форма однострочника, один pinned pull, запуск shim через dash без controlling TTY, подмена артефакта и отказ без согласия на APT. |
| DVT venv, `test_candidate.py` и `test_release.py` | `PASS` | 30 тестов. По независимому целевому набору DVT — 172 прошли, 8 пропущены. Ruff чист. |
| Distributor venv, `test_dvt_releases.py` | `PASS` | 13 тестов. Проверены ready stable, явная выдача RC в частном read API, отказы без готовой записи и совпадение JSON, POSIX-заголовков и хеша тела. |
| Пример raw allowlist и `git diff --check` | `PASS` | Проверены `main`, оба пути установщика и Compose прежнего мастера. |
| Полный чистый хост через реальный частный Distributor и Registry с новым signed pin | `NOT_RUN` | Нужна новая подпись конверта с обновлённым `bootstrap.py`. Старый pin остаётся неизменяемым. Нужны реальная установка Docker, браузер и reboot двух ОС именно для этого комплекта. |
| Публичный switch и внешний вход | `NOT_RUN` | До согласованной публикации проверить готовность stable на обеих ОС и соответствие raw bytes принятому GitHub `main`. |

Проверенные LF bytes рабочей копии:
`install.sh` SHA-256 `88ab4ea7eca2129c31da19f5e8032d0c3dad7bddfa4808914585d68f7f8d56d6`,
`services/installation_manager/host_bootstrap.py` SHA-256
`ee768e4f99b26899c7c8d346755ec83f66445bc1088cb11002305077acb0e8da`.
Этап остаётся `PARTIAL`. Наблюдения прежних прогонов привязаны к своим
исходным pin и не засчитываются как приёмка новой публичной цепочки.


### Итерация 6 — автоматические RC/stable и подписанная доставка S3

По согласованному пользователем изменению CI возвращён к автоматическому
потоку `4db99fd`. Для обоих режимов Bake собирает кандидаты один раз,
integration использует точные Linux amd64 leaf digest, promotion переносит
те же manifests без пересборки. Ручные gate, VM evidence receipt и отдельная
job загрузки assets удалены из активного CI. Остальные DEV, extension,
backup и deployment jobs сохранены.

**Режим выпуска образов.** При отсутствии signer и policy используется
прежний Registry-путь. Публичные trust и asset origin сами по себе не
включают подпись. RC автоматически получает version tags, stable
обновляет `latest` после проверки всех version tags. Конфликт immutable
version или расхождение built/tested roles/digest блокируют запись.
Порядок строк и кавычки lock-файла не участвуют в сравнении.

**Подписанная поставка.** Наличие signer или policy включает обязательную
упаковку. Частичная либо неверная конфигурация останавливает этот путь.
Build использует `dvt-release-build`, publish —
`dvt-release-publish`, обе области с `action: prepare` и штатным runner
`DVT`. Signer и policy доступны только build. Общий public trust
согласуется с reader, S3 writer credentials выдаются только publish.
Integration использует публичную копию trust из build artifact.

Временное вычислительное окружение строится из exact candidate manager.
Git, Skopeo и Python requirements устанавливаются автоматически, Alembic
берётся из exact source pin. Source экспортируется по конкретному SHA с
UI gitlink, рабочие `.env` и неотслеживаемые файлы в контейнер не
передаются. Кэш подписанного manifest применяется только при поддержке
CLI данным source, с повторной проверкой подписи, сроков и реальных
digest. Источники без нового CLI пересчитывают inventory.

После backend integration подписанный комплект проходит
`python -m scripts.release.test_install_candidate` с одним exact manifest.
Автоматическое E2E подтверждает чистую установку и первый вход, поэтому
требует `schema.initial_install=true`. Оно не закрывает полную матрицу
AT-01–AT-13 или все update-only переходы. Source прежнего RC без этого
CLI остаётся пригоден для режима выпуска образов.

В `release_images` assets записываются условно в единый bucket
`dvt-releases` по digest. Затем точный publisher проверяет клиентскую
доставку один раз, выполняет immutable version promotion и атомарно
записывает готовый manifest. Stable обновляет `latest` после успешной
готовности. Publisher автоматически получается по exact SHA
`1833d5c5b4278292de2891444442083e89a7d1ec` из
`$CI_SERVER_URL/extractor/denvic-distributor.git` через job token.
Ручные checkout и venv Distributor не нужны. Общие
`DVT_DISTRIBUTION_S3_*` настройки используются для assets и ready,
reader получает отдельные права чтения.

Явный `release-mode` передаётся из build в integration и release. Утрата
manifest, trust или receipt в signed режиме вызывает отказ. Receipt
передаётся отдельным artifact. Whitelist файлов исключает `.e2e-work`,
закрытые ключи, source checkout и credentials. Publisher дополнительно
сверяет packaged trust с независимой project policy. Его mounts
ограничены scripts, assets, locks, public trust, Registry auth и socket.
Writer Registry используется только внешним tool, устанавливаемый
стек читает публичные refs анонимно. Для signed E2E штатный Docker runner
должен разрешать один временный privileged DinD.

| Проверка | Результат | Наблюдение |
| --- | --- | --- |
| CICD venv, `test_dvt_release_promotion.py` и `test_gitlab_configuration.py` | `PASS` | 28 тестов. Проверены семантические locks, подменённый/неполный комплект, immutable collision до записи, последний недоступный source, повтор stable, версия до latest, signed ready boundary, partial signing и несовпадение независимого trust. Bash job fixture подтвердил отсутствие latest при ошибке publisher. |
| YAML multi-document parser, GitLab `!reference` и Bash syntax | `PASS` | Проверены root pipeline и обе изменённые jobs-группы. |
| Ruff и `git diff --check` | `PASS` | Проверены изменённые helpers и тесты. Git сообщает только о политике LF/CRLF. |
| Реальная сборка временного tool image | `PASS` | База — опубликованный manager leaf `sha256:3c20ba296fcc61a79ab4195004608b65b9a069c48ea58b7e7f0c66fe74f7c085`. Проверены Alembic, packaging, crypto, yaml, pydantic, imports release scripts, Git backend/UI и Skopeo 1.18.0, затем smoke без сети. |
| Реальная проверка clean export | `PASS` | Локальный source `cafa82578131274b4b89c2a3ab676098b048705a`, UI совпал с exact gitlink. Рабочий `.env` отсутствует в экспорте. |
| Registry platform inspection | `PASS` | Read-only Docker buildx прочитал реальный single-platform descriptor и config `linux/amd64`. Index path выбирает один Linux amd64 leaf и исключает attestations. |
| Полный новый signed GitLab pipeline с production S3 writer | `NOT_RUN` | Внешняя публикация в рамках исправления не запускалась. Понадобятся новый DVT tag с E2E CLI, job-token allowlist и согласованные переменные scopes. |
| Полная VM-матрица обновлённого exact manifest | `NOT_RUN` | Прежние результаты сохраняют привязку к своим pin. Полная матрица и SAC остаются открытыми. |

Изменены `dvt_cicd/.gitlab-ci.yml`, jobs `02-build-test.yml` и
`04-release-flow.yml`, helpers `promote_dvt_release.py`,
`lock_dvt_candidates.py`, `package_dvt_release.py`,
`distribute_dvt_release.py`, два целевых теста и руководства CI.
Имеющийся `publish_dvt_assets.py` переиспользуется.
`docs/DVT_RELEASE_GATE.md` содержит оба режима, первый RC с подготовкой
новых signer/trust/policy вне Git, exact Alembic schema, единый bucket,
scopes секретов и способ разрешить job token. Реализация DVT этим
CI-изменением не редактировалась. Этап остаётся `PARTIAL`.


**Исправление writable-состояния Buildx — 18 ноября.** Независимая
проверка обнаружила отказ `mkdir <DOCKER_CONFIG>/buildx: permission denied`
при запуске tool-контейнера под UID 1000 с read-only Registry config.
В `package_dvt_release.py` для E2E и в `distribute_dvt_release.py` для
publisher добавлен `BUILDX_CONFIG=/tmp/dvt-ci-buildx`. Auth-файл сохраняет
read-only mount. Реальный Linux `docker buildx inspect` прошёл под
UID/GID 1000 в обоих временных tool-образах с `network=none`.
Состояние создано в отдельном writable-каталоге, под `DOCKER_CONFIG`
новый каталог отсутствует, SHA-256 исходного config.json сохранился.
Собственный volume тестового CLI удалён. Сценарий не выполнял Registry
promotion или S3 publication.
