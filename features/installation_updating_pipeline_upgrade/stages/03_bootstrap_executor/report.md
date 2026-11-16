# Отчёт об этапе 03 — bootstrap, привязка и независимый исполнитель

- **Статус:** `READY_FOR_REVIEW`
- **Задание:** [task.md](./task.md)
- **Режим:** `IMPLEMENT`

## 1. Что сделано

- Добавил явную команду bootstrap `sudo bash ./install.sh --beta …`. Linux amd64 с systemd сохраняет identity, канонический каталог, Compose-проект и loopback-адрес HTTPS. Повтор принимает прежние параметры, а конфликтующий проект, каталог или привязка отклоняются до подготовки Docker. Bootstrap Compose и Compose операции хранятся раздельно.
- Защитил привязку одноразовым кодом на 10 минут, работу браузера устойчивой Secure/HttpOnly-сессией, проверкой Origin и CSRF, машинный вызов отдельным Bearer. Точка восстановления доступна через административный SSH-туннель с HTTPS и проверкой имени `localhost`. Старые привилегированные маршруты на opt-in экземпляре требуют авторизации и отвечают `410`.
- Настроил типизированные приём, статус по ID, активную операцию, историю, журнал и возобновление. HTTP 202 подтверждает сохранение в SQLite. Повтор с тем же ключом возвращает ID, другой активный запрос получает 409 и Location.
- Независимый одноразовый executor работает по закреплённому digest, вне Compose и без публикации портов. Хостовый bootstrap передаёт проверяемому исполнителю OS-release хоста, реальный Docker root, явно подтверждённый containerd root, каталоги данных и временной работы и host network namespace. HTTP принимает только закреплённый pin и вид операции.
- Executor берет host lock, проверяет два digest и совместимость журнала, записывает чекпоинт перед заменой мастера. Systemd поднимает следующий процесс того же исполнителя по активному ID после загрузки хоста. HTTPS-проверка подтверждает чтение нужного ID, instance и нового claim. Если цель недоступна, исполнитель возвращает исходный мастер и фиксирует отказ в журнале. Путь продолжения сохраняет намерение возврата.
- Открытая вкладка хранит ID и ключ повторного запроса в sessionStorage. При разрыве показывает прежний подтверждённый статус, после восстановления читает тот же ID. Работа включается флагом `--beta` и охватывает только стендовый Compose из одного мастера.

## 2. Изменённые файлы

| Путь | Что изменено |
| --- | --- |
| [install.sh](../../../../install.sh), [services/installation_manager/install.sh](../../../../services/installation_manager/install.sh) | Явный opt-in для обоих существующих entrypoints. |
| [host_bootstrap.py](../../../../services/installation_manager/host_bootstrap.py) | Хостовая проверка, сохранение параметров, локальный Docker CLI, кандидаты по digest, конфигурация Compose и systemd resume. |
| [candidate_main.py](../../../../services/installation_manager/candidate_main.py), [__main__.py](../../../../services/installation_manager/__main__.py) | Изолированные режимы HTTPS-мастера, загрузочной привязки, проверки журнала и временного исполнителя. |
| [candidate_auth.py](../../../../services/installation_manager/candidate_auth.py), [candidate_api.py](../../../../services/installation_manager/candidate_api.py) | Одноразовая привязка, постоянная сессия, машинный доступ, операции и ограниченный журнал. |
| [candidate_executor.py](../../../../services/installation_manager/candidate_executor.py), [operation_state.py](../../../../services/installation_manager/domain/operation_state.py) | Передача владения и проверка фактического мастера, продолжение и проверенный возврат исходного digest. |
| [frontend/src](../../../../services/installation_manager/frontend/src) | Определение контура, экран привязки и возобновляемого статуса кандидата. |
| [bootstrap_candidate.md](../../../../services/installation_manager/bootstrap_candidate.md) | Команда, TLS через SSH, доверительные предпосылки и контракт API. |
| [test_candidate.py](../../../../tests/unit/services/installation_manager/test_candidate.py) | Проверки авторизации, истечения срока, идемпотентности, сохранения при сбое запуска, возврата и запрета подготовки без согласия. |
| [artifacts](./artifacts), [AGENTS_CHANGELOGS.md](../../../../AGENTS_CHANGELOGS.md) | Изолированный стендовый сценарий и запись через `append_changelog.py`. |

## 3. Критерии приёмки

| Критерий | Статус | Подтверждение |
| --- | --- | --- |
| `SAC-01` | `PASS` | На Debian 13 и Ubuntu 24.04 повторен полный noninteractive вызов. Совпали HTTPS-адрес, порт, путь, Compose-проект и ID. Попытки занять этот проект из другого каталога и сменить порт сохранённого экземпляра отклонены. |
| `SAC-02` | `PASS` | Debian 13. После фактической замены мастера и смены boot ID по `systemctl reboot` прежняя HTTPS-cookie открыла операцию `fdd7a057-b6d6-478f-840c-f5ed9e9340bf`. Resume unit вернул `Result=success`, `ExecMainStatus=0`. Операция достигла `succeeded` с двумя последовательными владельцами. В Chrome с прежней историей тест отбросил ответ о новом принятом POST и оборвал GET. Вкладка подхватила новый ID, показала сообщение о перезапуске и восстановила тот же ID и URL. |
| `SAC-03` | `PASS` | На стендах анонимные запросы, повтор использованного кода, чужой Origin и запрос изменения без CSRF отклонены. Windows отдельно проверил истёкший код, неверный Host, браузерный контекст машинной авторизации и непередачу клиентом host paths. При недоступном Docker noninteractive unit test подтвердил, что команды установки пакетов без согласия не запускаются. |

## 4. Проверки

| Команда или проверка | Результат | Детали |
| --- | --- | --- |
| Windows project venv, `python -m pytest -q -p no:cacheprovider --tb=short tests/unit/services/installation_manager` | `PASS` | 79 прошли, 6 Linux-only пропущены, 13 предупреждений. `PYTHONPATH` установлен в абсолютный корень DVT. |
| Windows project venv, `python -m ruff format` и `python -m ruff check` для восьми изменённых Python-файлов мастера и тестов | `PASS` | Ошибок нет. Ruff предупредил о конфигурации импортов `core`. |
| `git -c submodule.services/ui.ignore=all diff --check` | `PASS` | Ошибок пробелов нет. Git сообщил о будущей нормализации рабочего `plan.md`, который изменяет мастер-агент. |
| Linux `bash -n` | `PASS` | Независимый запуск в `python:3.13-slim` без сети с read-only bind проверил оба `install.sh`, `handoff-smoke.sh` и `handoff-cleanup.sh`. |
| Windows `npm.cmd ci`, `npm.cmd run build` | `FAIL` | `npm ci` завершился. Vite в песочнице получил `EPERM` на `realpath` для `src/main.jsx`. |
| Штатный Dockerfile на Debian 13 и Ubuntu 24.04 | `PASS` | На обеих ВМ собран образ, включая обязательный Dockerfile-шаг `npm run build`. Сборка использовала `package.json` мастера. Собранный bundle загружен в Chrome на Debian. Отдельная строка npm из логов сборки не сохранялась. |
| Debian 13, `handoff-smoke.sh arm`, реальный `systemctl reboot`, `handoff-smoke.sh verify <fixture>` | `PASS` | До reboot цель реально запущена с новым container ID, executor в host network, без опубликованных портов и без метки Compose-проекта. После reboot новый claim, прежняя HTTPS-cookie, тот же ID и идемпотентный replay. |
| Ubuntu 24.04, `handoff-smoke.sh arm` и `handoff-smoke.sh verify-fallback <fixture>` | `PASS` | Для операции `e7b63dba-d82a-4eee-a8a1-1f77d593040d` целевой HTTP оставлен недоступным. Исходный digest восстановлен полным Compose, API с прежней сессией подтвердил `cancelled`, один claim и `manager_unavailable`. |
| Chrome/Playwright через SSH port forwarding на Debian | `PASS` | Проверены привязка и UI после потерянного ответа POST при наличии завершённой истории. Отдельный HTTPS smoke проверил тестовый CA и имя, а временный браузерный контекст не менял системное доверие. |
| Очистка стендов | `PASS` | В обоих уникальных fixture scope удалены Compose, выделенный systemd unit, временные Registry, data и точные loopback-теги. |
| Чистая Debian/Ubuntu без установленного Docker | `NOT_RUN` | На обеих выделенных ВМ Docker и Compose уже установлены. Реальный прогон установки APT-пакетов после согласия на чистом снимке остаётся открытым. |

## 5. Известные ограничения

- Stage 03 использует локальный одобренный дескриптор `manager-handoff-v1`. Образ, Compose и закрытые TLS-файлы тестового экземпляра готовятся отдельно. Подписанный продуктовый комплект этапа 02 сохранён как независимый контракт.
- Порог ресурсов и Compose соответствуют стенду из одного мастера. Проверки реального релиза, миграции БД, окна обслуживания, резервных копий и продуктового rollback относятся к последующим этапам.
- На обоих стендах проверены host networking и backing paths на ext4. Отдельные ФС, внешний Docker daemon, другие архитектуры и корпоративные TLS-профили не проверялись. Проверка работает с пути `localhost` через локальное подключение или SSH forwarding с тем же портом.

## 6. Вопросы мастер-агенту

- Нет.

## 7. Артефакты

- [handoff-smoke.sh](./artifacts/handoff-smoke.sh) — сборка из данного исходного дерева и подготовка сценариев reboot и fallback.
- [handoff_http.py](./artifacts/handoff_http.py) — HTTPS, аутентификация, этапы SQLite по API, Docker и проверка прежнего ID после смены процесса.
- [handoff-cleanup.sh](./artifacts/handoff-cleanup.sh) — очистка одного root-owned каталога изолированного smoke и привязанных fixture ресурсов.

## 8. Итерации исправлений

- Пока нет.
