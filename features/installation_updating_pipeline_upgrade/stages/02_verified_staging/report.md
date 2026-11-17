# Отчёт об этапе 02 — проверенный комплект и подготовка

- **Статус** `READY_FOR_REVIEW`
- **Задание** [task.md](task.md)
- **Режим** `IMPLEMENT`

## 1. Что сделано

- Определён подписанный контракт релиза v1. Закрепление по SHA-256 полных байтов манифеста, Ed25519 с доверенным корнем и сертификатами онлайн-ключей, срок действия и отзыв, платформенные digest образов, Compose/Bootstrap, требования профиля и разрешённая матрица ревизий. Добавлен воспроизводимый комплект с публичными тестовыми ключами.
- `VerifiedStaging.prepare` использует `OperationStore`, `ReleasePin` и сохранённый `config_id`. При повторе проверяет кеш и сохраняет тот же ID и pin. После проверок пишет `PREPARED` и приватный артефакт плана, отдельно указывая подготовленный, применённый и наблюдаемый релизы. Штатные маршруты установки и обновления на уровне приложения используют прежний путь.
- Проверки Compose охватывают все образы и разрешённый активный профиль. Staging запускает Compose с заданным проектом, выбранным окружением и пустым env-файлом. Сохраняются секреты и дополнительные публичные origins. Сравниваются фактические образы, тома, сети, порты, инфраструктурные параметры и реквизиты. При первом запуске допускается единственный проверенный bootstrap master. Рабочие файлы и контейнеры во время staging не переключаются.
- Выполняются фактические HTTPS-запросы и Docker pull по платформенному digest. Для временных ошибок предусмотрены limited retry и один общий дедлайн. Таймаут завершает группу процессов Compose. Проверка места и inode агрегирует резервы по устройствам, учитывает Docker, containerd, данные, staging, временный каталог, копию, кеш, распаковку и уже занятое место.

## 2. Изменённые файлы

| Путь | Что изменено |
| --- | --- |
| `services/installation_manager/domain/release_manifest.py` | Версионированный JSON-контракт, модели релиза, профиля и переходов. |
| `services/installation_manager/infrastructure/release_verification.py` | Проверка pin, цепочки доверия, времени, отзыва и файлов. |
| `services/installation_manager/application/verified_staging.py` | Подготовка по ID и checkpoint по результату проверок. |
| `services/installation_manager/infrastructure/staging_{artifacts,compose}.py` | Защищённые артефакты, окружение, конфигурация Compose и сравнение работающей инфраструктуры. |
| `services/installation_manager/infrastructure/staging_{commands,docker,downloads,host}.py` | Deadline, subprocess-группа, фактические загрузки, Docker и проверки хоста. |
| `services/installation_manager/{Dockerfile,requirements.txt,verified_staging.md}` | Зависимости для opt-in подготовки, контракт для Distributor и следующих этапов. |
| `tests/data/installation_manager/verified_staging/` | Генератор и подписанные beta fixtures. |
| `tests/unit/services/installation_manager/{application/test_verified_staging,infrastructure/test_staging_io}.py` | Тесты отказов, продолжения, изоляции, правок инфраструктуры и ресурсов. |
| `features/installation_updating_pipeline_upgrade/stages/02_verified_staging/artifacts/` | Воспроизводимые Docker smoke для обоих профилей отказов. |
| `AGENTS_CHANGELOGS.md` | Запись через `dvt-project-ops`. |

## 3. Критерии приёмки

| Критерий | Статус | Подтверждение |
| --- | --- | --- |
| `SAC-01` | `PASS` | Подмена подписи, корня, manifest, Compose или bootstrap, несовместимые версия, платформа или переход, внешний Compose-файл, несовпадение AI MCP и рискованные изменения портов, сетей, образов либо монтирований останавливаются до pull. Проверены разрешённая ротация и отзыв ключа. |
| `SAC-02` | `PASS` | Debian 13 и Ubuntu 24.04 с Docker 29.10.0/Compose 5.7.1. После неверного CA, недоступного Registry и выявленного дефицита места или inode контрольный HTTP-сервис продолжал отвечать, рабочий `.env` сохранился. Повтор после временного сбоя использует тот же ID и манифест даже при изменении байтов по исходному URL. На Debian отдельная Docker bridge с реальным MTU 1280 передала 65 536 байт после одного принудительного разрыва HTTPS. |
| `SAC-03` | `PASS` | Повторяемая проверка Compose на обеих ВМ с пустым секретом во внешнем env использовала сохранённое значение. Проверена обработка буквальных `$` и `$$`, наличие секрета в обоих компонентах, отсутствие значения в плане и безопасных ошибках. В Linux оба варианта молчащей группы процессов завершились по дедлайну, в том числе когда родитель вышел раньше потомка. |

## 4. Проверки

| Проверка | Результат | Детали |
| --- | --- | --- |
| Windows venv, `python -m pytest -q -p no:cacheprovider --tb=short tests/unit/services/installation_manager` | `PASS` | **71 прошёл, 6 Linux-only пропущены, 12 предупреждений**, 6,72 с. Прежний launcher сообщает, что не нашёл базовый executable uv по сохранённому пути, после чего выполняется venv. |
| Windows venv, `python -m ruff format <файлы этапа>`, `python -m ruff check <файлы этапа>` | `PASS` | Клиент предупредил о прежнем пересечении секций импортов `core`. Итоговых нарушений нет. |
| Docker Desktop Linux Engine 29.1.3, `python -m pytest -q -p no:cacheprovider /case/tests/unit/services/installation_manager` | `PASS` | **41 сценарий этапа 02**, 1,52 с. Контейнер — UID/GID `65534`, без сети, доступа к сокету Docker и хостовым файлам. |
| Compose 2.40.3-desktop.1 и 5.7.1, `compose config --format json --no-env-resolution` | `PASS` | Обе версии удваивают каждый буквальный знак `$` в JSON для последующей интерполяции. Снятие ровно одного уровня экранирования восстанавливает исходное значение, включая последовательности `$$`. |
| Изолированные Debian 13, Ubuntu 24.04 LTS, `artifacts/release-smoke/run.sh` | `PASS` | В обоих: `self-signed-cert → tls`, `registry-unreachable → registry_unavailable`, `space-deficit → disk_space`, `inode-deficit → inodes`, `retry-and-pinned-image-preflight → prepared`. Оба профиля используют фактические хостовые ФС и OS-release, включая Debian-образ исполнителя на Ubuntu. Положительный сценарий загрузил небольшой pinned образ BusyBox и использовал Docker Compose для наблюдения контрольных контейнеров. |
| Изолированный Debian 13, `artifacts/mtu/run.sh` | `PASS` | Отдельная внутренняя bridge с MTU 1280, локальный HTTPS и временный CA. После первого принудительного разрыва получен исходный payload 65 536 байт по тому же URL. |
| Промежуточные прогоны | `FAIL` | На Windows fixture первоначально сравнивал Linux-путь с Windows Path, затем после ужесточения `HostPaths` не передавал тестовый абсолютный os-release. Оба исправлены. В первом Linux-контексте отсутствовал `core.security`. Во втором тест проверял состояние потомка сразу после SIGKILL. Исправлены состав контекста и наблюдение завершения в пределах 300 мс. На первых двух удалённых прогонах проверка секрета перепутала сериализацию Compose с эффективным значением. Исправлена нормализация и повторены оба прогона. |
| `git diff --check --ignore-submodules=all` | `PASS` | В рабочем `plan.md` есть изменение мастера. Git сообщает о преобразовании его LF в CRLF. |
| Реальное исчерпание ext4 на ВМ, исторический сетевой blackhole, целые AT-02/03 на продуктовом кандидате и сквозной AT-10 | `NOT_RUN` | Дефициты в smoke вызваны расчётом по переоценённому подписанному профилю поверх реальных ФС. Реальная низкая MTU проверялась с контролируемым сетевым разрывом. Рабочий сервис был тестовым BusyBox, функциональные DVT/Gateway/AI MCP и полный end-to-end входят в следующие этапы и этап 10. |

Команды Windows из корня DVT.

```powershell
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --tb=short tests/unit/services/installation_manager
$stage02Py = @((Get-ChildItem services/installation_manager/infrastructure/staging_*.py).FullName) + @(
  'services/installation_manager/application/verified_staging.py',
  'services/installation_manager/domain/release_manifest.py',
  'services/installation_manager/infrastructure/release_verification.py',
  'tests/unit/services/installation_manager/application/test_verified_staging.py',
  'tests/unit/services/installation_manager/infrastructure/test_staging_io.py',
  'tests/data/installation_manager/verified_staging/fixtures.py'
)
.\.venv\Scripts\python.exe -m ruff format @stage02Py
.\.venv\Scripts\python.exe -m ruff check @stage02Py
git diff --check --ignore-submodules=all
```

Контекст локального Linux был собран из `core/{__init__,security}.py`, `services/__init__.py`, файлов и `__init__.py` используемых пакетов Installation Manager, двух модульных тестов этапа и директории подписанных fixtures. Базовый образ `python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90`. Тестовая venv `/opt/test-venv` содержала `pytest==8.4.0 pydantic==2.11.5 cryptography==50.0.1 packaging==25.0 PyYAML==6.0.3`. `PYTHONPATH=/case`. Команды Docker.

```powershell
docker build --quiet --tag $stage02Image $stage02Context
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,mode=1777 $stage02Image /opt/test-venv/bin/python -m pytest -q -p no:cacheprovider /case/tests/unit/services/installation_manager
docker image rm $stage02Image
```

Для воспроизведения ВМ используйте файлы [release-smoke](artifacts/release-smoke/) и [mtu](artifacts/mtu/). Для каждого теста подготовьте отдельный на временном диске каталог `work=$(mktemp -d /tmp/dvt-staging-test.XXXXXXXX)`. Перенесите в его корень три файла выбранного harness и исходники со структурой выше, включая `core` и `services`. Для release-smoke также нужен `tests/data/installation_manager/verified_staging/fixtures.py`. Выполните `sudo bash "$work/run.sh" "$work"` на выделенной ВМ. Harness проверяет уникальность имени Docker-ресурсов и выполняет очистку. Временный контекст и временный CA удаляются тем же тестовым циклом. Системные пакеты на ВМ не устанавливались.

## 5. Контракт для последующих этапов и ограничения

- См. [контракт Verified Staging](../../../../services/installation_manager/verified_staging.md). `ObservedRelease` требует независимо подтверждённые версию, ревизию и полный набор digest фактических запущенных сервисов. Согласованный применённый `ReleasePin` передаётся отдельно. Наличие старого тега или значения в `.env` не подтверждает наблюдаемую версию. Legacy передаёт оба pin как `None` только по типизированному внутреннему каналу этапа 06 после независимого сопоставления с известным исходным выпуском.
- В beta политика доверия поддерживает пакеты в пределах времени действия ключа и манифеста. Владелец окружения подаёт trust roots и реальный путь containerd. Для применения требуются профиль продукта и сформированный CI комплект с реальными digest и консервативными, измеренными размерами. Пороги в тесте предназначены тестовым контейнерам.
- Ограничение процесса относится к Linux process group клиента Compose. Сетевой обмен Docker daemon происходит отдельно. Статус daemon и завершение фоновой работы Docker после разрыва CLI не доказывались. Оценка ресурсов проверяется до и после pull. Изолированный тест не заполнял общий диск, чтобы не затронуть хост.
- Стартовый мастер, окно обслуживания, миграции, переключение применённого указателя, fallback со старого мастера и офлайн-импорт принадлежат следующим этапам.

## 6. Вопросы мастер-агенту

- Нет.

## 7. Артефакты

- [artifacts/release-smoke](artifacts/release-smoke/) — подготовка и контролируемые ошибки на отдельной ВМ.
- [artifacts/mtu](artifacts/mtu/) — проверка HTTPS-повтора на выделенной Docker bridge.
- [Подписанные beta fixtures](../../../../tests/data/installation_manager/verified_staging/) — воспроизводимая проверка контракта.

## 8. Итерации исправлений

- Пока нет.
