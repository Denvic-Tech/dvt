# Отчёт об этапе 01 — постоянное состояние экземпляра и операций

- **Статус** `READY_FOR_REVIEW`
- **Задание** [task.md](./task.md)
- **Режим** `IMPLEMENT`, затем `FIX` (итерация 1)

## 1. Что сделано

- Фиксируется identity с ID установки, каталогом данных, Compose-проектом, привязкой мастера и публичным адресом. Повторная запись эквивалентных данных возвращает исходную identity. Конфликт не меняет состояние.
- Намерение и первое событие записываются до возврата из `admit`. SQLite сериализует изменения экземпляра через `BEGIN IMMEDIATE`. Уникальный индекс защищает единственное активное бронирование. Версия формата — `1`; несовместимый формат отклоняется.
- Исполнитель отдельно захватывает блокировку экземпляра. Факт захвата фиксируется уникальным ID попытки и временем. Журнал чекапойнтов и снимок состояния обновляются одной транзакцией. После ошибки восстановления активное бронирование сохраняется.
- Тесты установщика включают реальные независимые процессы и проверку прав файлов в Linux. Действующие маршруты прошли регрессионные тесты.

## 2. Изменённые файлы

| Путь | Что изменено |
| --- | --- |
| `services/installation_manager/domain/operation_state.py` | Типизированные identity, запросы, версии, наблюдения, события и правила переходов. |
| `services/installation_manager/infrastructure/operation_store.py` | Версионированное SQLite-хранилище, admission, чтение по ID, журнал и проверка актуальности владельца. |
| `services/installation_manager/infrastructure/operation_files.py` | Проверка владельца и режимов файлов, межпроцессная блокировка Linux, совместимая блокировка для локальных Windows-тестов. |
| `tests/unit/services/installation_manager/infrastructure/test_operation_store.py` | Девять сценариев, включая одновременный admission, остановку владельца, секреты и режимы файлов. |
| `AGENTS_CHANGELOGS.md` | Запись на русском через `dvt-project-ops`. |

## 3. Критерии приёмки

| Критерий | Статус | Подтверждение |
| --- | --- | --- |
| `SAC-01` | `PASS` | Новый объект хранилища перечитывает identity. Эквивалентный URL нормализуется. Изменение любого из шести полей вызывает конфликт. Байты SQLite и mtime сохраняются. |
| `SAC-02` | `PASS` | Два независимых процесса одновременно принимают запрос. Повтор ключа возвращает один ID, разные ключи дают один ID и один конфликт. На Linux второй процесс получает отказ, пока первый держит `flock`. После `SIGKILL` следующий процесс читает исходный checkpoint, получает новый ID попытки и завершает ту же операцию. История видна после повторного открытия. Другой каталог с другой identity допускает собственную операцию параллельно. |
| `SAC-03` | `PASS` | Изменённая конфигурация, ссылка на защищённый конфиг и digest манифеста дают конфликт на прежнем ID. Устаревший handle после повторного захвата в том же процессе не пишет checkpoint. Терминальная операция освобождает бронирование, повтор прежнего ключа возвращает её и при наличии новой активной операции. Ошибка восстановления держит активный ID. |
| `SAC-04` | `PASS` | На Linux проверены `0700` для каталога и `0600` для SQLite, rollback-журнала и файла блокировки, UID владельца и отказ при небезопасном режиме и при symlink/hardlink. Неизвестная версия отклоняется без переписи. Синтетический ключ отсутствует в файле БД в открытом виде. Модель отвергает учётные данные в URL и произвольный диагностический текст. Четыре действующих API-теста прошли. |

## 4. Проверки

| Команда или проверка | Результат | Детали |
| --- | --- | --- |
| `.\.venv\Scripts\python.exe -m pytest tests/unit/services/installation_manager`, исходное состояние | `PASS` | 18 тестов. |
| Та же команда, первый запуск после правок | `FAIL` | Windows-песочница возвращала `WinError 5` для строгого `Path.resolve` на каталогах fixture. Для Windows используется нестрогий `resolve`, операции с файлами проверяют существование, Linux сохраняет строгую канонизацию. |
| Та же команда, итоговый запуск | `PASS` | 25 прошли, 2 проверки прав и ссылок пропущены на Windows. Pytest сообщил об ограничении записи кеша и предупреждениях зависимостей. |
| `.\.venv\Scripts\python.exe -m ruff format` и `-m ruff check` по четырём Python-файлам этапа | `PASS` | Проверка Ruff прошла. Ruff выдал предупреждение о существующем пересечении секций импортов `core`. |
| Pytest в Linux-контейнере, см. команды ниже | `PASS` | Python 3.13.18, pytest 8.4.0, 9 прошли. Контейнер запущен с UID/GID `65534`, без сети, доступа к Docker socket, примонтированных файлов хоста и привилегий. Контейнер, тестовый образ и рабочий каталог сборки удалены. |
| `git diff --check --ignore-submodules=all` | `PASS` | Git сообщил о преобразовании LF/CRLF в изменённом мастером `plan.md`. |
| Перезагрузка Linux-хоста с состоянием на постоянном диске, пересоздание мастера и сквозной AT-05 | `NOT_RUN` | Этапы 03 и 10. Здесь воспроизведён обрыв процесса с продолжением на том же Linux ФС. |

Команды запуска из корня репозитория.

```powershell
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m pytest tests/unit/services/installation_manager
$stage01Files = @(
  'services/installation_manager/domain/operation_state.py',
  'services/installation_manager/infrastructure/operation_files.py',
  'services/installation_manager/infrastructure/operation_store.py',
  'tests/unit/services/installation_manager/infrastructure/test_operation_store.py'
)
.\.venv\Scripts\python.exe -m ruff format @stage01Files
.\.venv\Scripts\python.exe -m ruff check @stage01Files
git diff --check --ignore-submodules=all
```

В `$stage01Context` были скопированы четыре Python-файла выше и `__init__.py` каталогов `services/`, `services/installation_manager/`, `domain/` и `infrastructure/` под теми же относительными путями. Тест использовал встроенный временный каталог pytest на `/tmp` внутри контейнера. Содержимое Dockerfile.

```dockerfile
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
RUN python -m venv /opt/test-venv && /opt/test-venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir pytest==8.4.0
WORKDIR /case
COPY services/ /case/services/
COPY tests/ /case/tests/
ENV PYTHONPATH=/case PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
```

```powershell
docker pull python:3.13-slim
docker build --quiet --tag $stage01Name $stage01Context
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,mode=1777 $stage01Name /opt/test-venv/bin/python -m pytest -p no:cacheprovider -v /case/tests/unit/services/installation_manager/infrastructure/test_operation_store.py
docker image rm $stage01Name
```

## 5. Контракт для этапов 02–09 и ограничения

- **Путь и формат.** `OperationStore.for_host(data_dir)` открывает `<DVT_LIB_DIR>/.installation-state` в существующем каталоге данных. Из контейнера `OperationStore(state_dir)` должен указывать на bind mount того же каталога хоста. Хостовый путь в `InstanceIdentity` вычисляется bootstrap через `Path.resolve(strict=True)` до передачи в контейнер. В v1 требуется локальная ФС с поддержкой блокировок SQLite и `flock`. Каталог имеет режим `0700`. Читающие и пишущие процессы должны работать под одним эффективным UID. `journal.sqlite3` с `application_id=0x44565449`, `user_version=1` использует rollback `DELETE` и `synchronous=EXTRA`. Файл `executor.lock` занимает один inode на весь срок жизни экземпляра. Родительский каталог и файлы состояния управляются доверенными процессами. Смена inode блокировки, копирование открытого журнала и перенос каталога требуют отдельного протокола.
- **Регистрация экземпляра.** `identity()` возвращает identity или `None`, `establish_identity(proposal)` записывает первый согласованный набор или поднимает `IdentityConflict`. Модель принимает ненулевой UUID, нормализованный абсолютный Linux-путь, имя Compose-проекта, IP привязки и TCP-порт. Главный публичный адрес — HTTP(S) origin без учётных данных, path, query и fragment. Этап 06 сохраняет дополнительные старые URL в защищённой конфигурации.
- **Приём.** `admit(OperationRequest, idempotency_key=...)` возвращает `Operation` и `Operation.id` после успешного коммита. Авторизующий слой проверяет права до обращения к журналу и перед выдачей `OperationConflict.operation_id`. Повтор валиден и после терминальной стадии. Закреплённый `ReleasePin(release_id, manifest_digest)` и параметры запроса сравниваются в канонической форме. Операторские настройки могут ссылаться на неизменяемый защищённый пакет по `config_id`. `bundle_id` и `restore_backup_id` закрепляют исходные артефакты. `artifact_path(ArtifactKind, UUID)` разрешает `artifacts/{bundle,staging,backup,config}/<uuid>`. Создание, проверка целостности, защита содержимого и запрет перезаписи артефактов принадлежат производящим этапам.
- **Исполнение.** `with store.claim(operation_id) as owner` удерживает блокировку до выхода и сохраняет `owner.record` с уникальным ID попытки и UTC-временем. Записи владельца остаются для истории. `owner.checkpoint(Checkpoint(...))` проверяет живой handle, текущую попытку и допустимость перехода. После повторного захвата исполнитель сверяет внешнее состояние перед действиями. Восстановление при сбое оставляет ту же операцию активной в `RECOVERY_REQUIRED`. Успешный выход проходит верификацию и `RESUMING`. Отмена на этапе обслуживания или копии требует результата `VERIFIED` о безопасном возврате. Схема переходов задаёт форму журнала. Фактическое подтверждение готовности, наличия копии, совместимости схемы и возобновления приёма выполняют последующие этапы.
- **Условия миграции.** Прямой переход `PREPARED → MIGRATING` поддерживается для первичной установки. Прямой `PREPARED → RECOVERING` предназначен для `MANAGER_RECOVERY` и `RESTORE`. При обновлении используется `PREPARED → MAINTENANCE → BACKUP → MIGRATING`. До записи `MIGRATING` нужен ранее сохранённый `observation.backup_id`, в том числе при повторном захвате операции и продолжении из `RECOVERING`. Ссылка, переданная впервые или заменённая в том же checkpoint, приводит к отказу до записи снимка и события.
- **Чтение и приватность.** `get(id)`, `active()`, `history(before=UUID, limit=...)`, `events(id, after=cursor, limit=...)`. `history` сортируется от новых к старым по порядку admission и включает текущую операцию. События возрастают по целочисленному курсору; максимум 1000 записей за вызов. При переходе событие содержит предыдущую стадию и длительность. Снимок `Operation.observation` объединяет последние известные структурированные версии, digest и UUID артефактов. Писать можно только типизированные поля и известные коды, а идемпотентный ключ хранится как SHA-256. Вывод Compose, приватные URL, содержимое конфигурации и секреты переходят по отдельному защищённому каналу.
- **Дочерние процессы.** Дескриптор `flock` не переживает `exec`. Долго живущий дочерний процесс, созданный raw `fork` без `exec`, может удержать унаследованный дескриптор после смерти родителя. Исполнитель должен запускать команды с закрытием посторонних дескрипторов, как при обычном `subprocess`.

## 6. Вопросы мастер-агенту

- Нет. Для этапа 03 требуется выбрать общий UID и подключить один каталог хоста к мастеру и исполнителю.

## 7. Артефакты

- Результаты и команды приведены выше.

## 8. Итерации исправлений

### Итерация 1 — 16 ноября 2026

- **Замечание** [fix_task.md](./fix_task.md). Обновление могло войти в миграцию сразу из `PREPARED` или через восстановление без зарегистрированной копии.
- **Воспроизведение до правки** `FAIL`. Команда `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/unit/services/installation_manager/infrastructure/test_operation_store.py -k "rejects_shortcuts or committed_backup or install_can_migrate or dedicated_recovery"` под Windows дала 5 отказов и 3 успешных проверки. API принимал прямые переходы обновления, вход в миграцию без ссылки из `BACKUP` и `RECOVERING`, а также замену ссылки при входе в миграцию.
- **Исправление** `transition_allowed` читает вид операции и ранее сохранённое наблюдение из записи, открытой в транзакции чекпоинта. В тестах отклонённый переход сохраняет исходную стадию, снимок и список событий. Первичная установка по-прежнему может войти в миграцию после подготовки; отдельные операции восстановления начинают с `RECOVERING`. Штатный путь обновления и продолжение после повторного захвата используют сохранённый ID копии.
- **Изменённые файлы** `domain/operation_state.py`, `infrastructure/operation_store.py`, `tests/unit/services/installation_manager/infrastructure/test_operation_store.py`, `AGENTS_CHANGELOGS.md`.
- **Критерий исправления** `PASS`. Регрессии включают запрет перехода из `PREPARED` даже при уже записанной ссылке, отказ при передаче ссылки впервые или её подмене в запросе на миграцию, прямой путь установки и возобновление штатного обновления с прежним ID копии.

| Команда или проверка | Результат | Детали |
| --- | --- | --- |
| `.\.venv\Scripts\python.exe -m pytest tests/unit/services/installation_manager` | `PASS` | 34 прошли, 2 Linux-проверки пропущены на Windows. |
| Изолированный Linux-тест операции из §4 | `PASS` | 18 прошли, включая Linux-проверки владения, прав и новые переходы. |
| Ruff по четырём Python-файлам из §4 | `PASS` | `ruff format` и `ruff check` завершились успешно. |
| `git diff --check --ignore-submodules=all` | `PASS` | Предупреждение LF/CRLF для `plan.md`. |
| Физическая проверка копии и проверка БД | `NOT_RUN` | Эти проверки выполняются в этапах 04–06. |
