# Офлайн-установка и обновление DVT

Поддерживаемая матрица архивов v1 — Linux amd64, Debian 13 и Ubuntu 24.04, базовый
профиль или `ai-mcp` из манифеста релиза. Образы должны помещаться в локальный
containerd image store Docker. Минимумы Docker Engine, Compose, CPU, RAM, дискового
пространства и число воркеров задаёт подписанный релиз. Архив обновления привязан
к той же ОС и профилю. Установка Docker использует локальные `.deb`, а переход
DVT сохраняет существующие PostgreSQL и Valkey.

## Подготовка доверенного CLI

На доверенной подключённой машине подготовьте копию принятой версии DVT, публичный
`release-trust.json`, Python и колёса. Корни доверия и копию CLI получите по
принятому каналу поставки до обработки входного архива. Выполнять скрипты из
непроверенного архива для его проверки не требуется. Соберите wheelhouse на той
же ОС, архитектуре и версии Python, что и офлайн-хост. На Debian/Ubuntu нужны
системный Python 3.11+ и пакет `python3-venv` или их доверенная независимая поставка.

```sh
# На подключённой машине с ABI получателя
python3 -m venv ./wheel-prep
./wheel-prep/bin/python -m pip download --only-binary=:all: \
  --dest ./dvt-host-wheels -r "$DVT_CHECKOUT/services/installation_manager/requirements.txt"
# После переноса доверенной копии CLI, requirements и wheels на получателя
python3 -m venv "$DVT_VENV"
"$DVT_VENV/bin/python" -m pip install --no-index --only-binary=:all: \
  --find-links "$DVT_HOST_WHEELS" -r "$DVT_CHECKOUT/services/installation_manager/requirements.txt"
```

Доверенный каталог содержит `pyproject.toml`, `services/__init__.py` и
`services/installation_manager`. Политика имеет вид
`{"roots":{"id":"<64 hex>"},"revoked_signers":[]}`. Никогда не берите корень
из самого архива. Машине нужны локальные сертификат, закрытый ключ и сертификат
CA защищённого мастера с именем localhost. Строгий офлайн-режим сохраняет этот
локальный HTTPS канал. Distributor, Registry, DNS и публичные TLS-сертификаты
на получателе не нужны. Для проверки готовности используйте доступный без
внешнего DNS HTTP origin, например `http://127.0.0.1:8080`.

## Чистая установка

Укажите закрытый JSON со строковыми значениями конфигурации. Задайте
`DVT_EXTERNAL_PORT`, PostgreSQL и Valkey settings для принятого Compose.
Для `ai-mcp` укажите `DVT_AI_MCP_ENABLED=true`, `COMPOSE_PROFILES=ai-mcp` и
собственный `DVT_AI_MCP_INTERNAL_SECRET`. Для установки и обновления на RC передайте `--confirm-rc`.

```sh
sudo env PYTHONPATH="$DVT_CHECKOUT" "$DVT_VENV/bin/python" \
  -m services.installation_manager.application.offline_bundles install \
  --dir "$DVT_DATA" --bundle "$INSTALL_ARCHIVE" --trust "$DVT_TRUST" \
  --config "$DVT_CONFIGURATION" --public-url http://127.0.0.1:8080 \
  --cert "$DVT_TLS/cert.pem" --key "$DVT_TLS/key.pem" --ca "$DVT_TLS/ca.pem" \
  --containerd-root /var/lib/containerd
```

Разрешите установку Docker из архива флагом `--install-docker`, если на хосте
Docker/Compose ещё отсутствуют. Существующий совместимый Docker не заменяется.
APT моделирует установку только из локальных пакетов и базы установленных
пакетов. Если базовая ОС требует дополнительных системных зависимостей, их
поставляют в заявленном профиле или заранее устанавливают доверенно локально.
На Docker с отключённым containerd store включите его до подготовки и передайте
фактический `--containerd-root`. Для готового Docker установщик предварительно
проверяет Compose и бюджеты до загрузки образов. После проверки записывается
один operation ID. Штатный executor завершает установку по тому же ID.

```sh
sudo python3 "$DVT_DATA/.bootstrap/host_bootstrap.py" resume --dir "$DVT_DATA"
```

## Обновление и восстановление

```sh
sudo env PYTHONPATH="$DVT_CHECKOUT" "$DVT_VENV/bin/python" \
  -m services.installation_manager.application.offline_bundles update \
  --dir "$DVT_DATA" --bundle "$UPDATE_ARCHIVE"
sudo python3 "$DVT_DATA/.bootstrap/host_bootstrap.py" maintenance \
  --dir "$DVT_DATA" --operation-id "$OPERATION_ID"
```

Update берёт доверие из защищённой host-конфигурации или override, сверяет
рабочие Compose и конфигурацию с закреплённым состоянием, наблюдает фактический
Gateway, PostgreSQL и его ревизию. Старый bootstrap сначала проходит поддерживаемый
переход из [руководства по восстановлению](../../services/installation_manager/recovery.md).
Управляемый экземпляр должен иметь закреплённый локальный executor с поддержкой
подписанных офлайн-архивов. CLI проверяет эту возможность до допуска операции.
Исторический архив без подписи нужно заменить текущим подписанным архивом.
`install.sh`, `update.sh` передают те же аргументы CLI с `--bundle`.
Для повторной подготовки укажите `--operation-id` вместо `--bundle` и сохраните
тот же выбор. Применение, отмена, резервная копия и возврат к исходному состоянию
используют те же проверки и команды, что онлайн.

Для восстановления на чистом хосте сначала поставьте локальный Docker и импортируйте
образы исходного комплекта. Команда наполняет локальный кэш и не создаёт экземпляр.

```sh
sudo env PYTHONPATH="$DVT_CHECKOUT" "$DVT_VENV/bin/python" \
  -m services.installation_manager.application.offline_bundles restore-images \
  --dir "$DVT_DATA" --bundle "$SOURCE_ARCHIVE" --trust "$DVT_TRUST" \
  --containerd-root /var/lib/containerd
```

Затем пройдите `portable_restore plan/restore-data` и `restore_runtime start/finalize`
или эквивалентный подтверждённый host CLI из руководства. У полного восстановления
есть отдельное подтверждение digest копии и точки отсечения данных. Вместе с
копией сохраните подписанный архив исходного комплекта, чтобы наполнить кэш
нового хоста. Транспортный кэш образов в копию не входит.

## Проверки и границы профиля

- `verify --bundle …` проверяет подписи, платформу, контрольные суммы, OCI
  структуру и Docker-пакеты без импорта и запуска. Распаковка идёт в закрытый
  временный каталог. Принимаются только обычные USTAR-файлы из подписанного
  списка, до 4096 файлов, до 8 ГиБ на файл и до 64 ГиБ суммарно. Проверяются
  свободные байты и inode. Ссылки, PAX/GNU metadata и обход путей отклоняются.
- Архив передаёт исходный манифест ReadyRelease, Compose и bootstrap ровно по
  подписанным хешам. Для всех ролей, включая профили и один общий образ
  Gateway/migrate, проверяются оригинальные leaf digest, OCI config и слои.
  Docker после импорта должен показать тот же RepoDigest, leaf descriptor,
  платформу и ID слоёв. Compose применяет ссылки по digest с `--pull never`.
- Расширения профиля поставляются как локальные каталоги с `pyproject.toml`
  и транзитивной wheelhouse в `.dvt/wheels`. Подготовка проверяет их в целевых
  Gateway и worker образах с `--network=none`. В миграции и приложении
  включается строгий pip только для локальных колёс, прямые URL запрещены
  также в метаданных wheel. В обновлении код существующих расширений сверяется
  с подписанным профилем. Поддерживаются добавление новых расширений и
  недостающих колёс для существующей версии. Замена кода существующего
  расширения и профили с ожидающими удалениями требуют отдельного перехода.
- Обработчик копирует пакеты в рабочий каталог только после подтверждённой
  подготовки и, при обновлении, проверенной копии. Проверки совместимости
  расширений и повторная проверка перед началом обслуживания оставляют
  действующий стек доступным при неполном архиве.
