# Локальная проверка release gate

## Выпуск и конфигурация

- Bake `--print`, группа `release` — восемь целей, каждая `linux/amd64`.
  При намеренно заданном постороннем `UI_BUILD_CONTEXT` цель UI использовала
  `services/ui`, `Dockerfile`, `VITE_API_BASE_URL=/api`.
- Signed-Compose fixture принят `docker compose --profile '*' config --images`.
  Получены 11 ролей, все ссылки по digest, Gateway и migrate имеют одну ссылку.
  Это проверка синтаксиса со специально созданными ссылками.
- YAML+GitLab `!reference` локально разобраны. Блоки shell release jobs и
  `capture_vm.sh` прошли `bash -n` без исполнения сценариев.
- Источник `7fe257b129adb329faea503e2e17af6eaf4d2be9` фиксирует UI gitlink
  `543b246ce6abf673fc4a41943365f5d853650377`. Alembic `0070 (head)`.
- GitLab hosted CI validator и реальный production pipeline — `NOT_RUN`.

## Сухая проверка отказов

| Вход или отказ | Выход | Наблюдение |
| --- | --- | --- |
| Нет Valkey в манифесте, receipt совпадает с неполными байтами | `1` | Проверка комплекта завершилась до Registry. |
| Манифест подменён после receipt | `1` | Promotion не обращался к Registry, Publisher dry run не обратился к Git/HTTPS/S3. |
| Верные данные для preflight | `0` | Promotion dry run проверил источники и version tags, копий не создал. Distributor dry run не создавал S3-клиент. |
| Изменён локальный файл перед upload | Ошибка | Stage assets сверил оба файла с signed descriptors до обращения к S3. При исправных байтах оба объекта переданы с `IfNoneMatch=*`. |
| Тестовый отказ копирования второго version tag | `1` | Первый тестовый tag мог сохраниться. Job с `set -Eeuo pipefail` вызывает writer только после успеха команды promotion. |
| Не пройден e2e, нет клиентского bootstrap или слоя, изменились Compose или bootstrap | Ошибка | Production ReadyStore не вызвал условную запись, реальный FastAPI route сохранил пустой список. |
| Доставлены точные signed bytes и receipt | `0` | Адаптер показал один условный Put `IfNoneMatch=*`, повтор идемпотентен. Запрос по digest возвращает только записанные bytes. |

В этих отказах Registry, HTTP, Git и S3 изолированы тестовыми адаптерами.
Команда издателя, валидация набора и шаблон готовности используются из
рабочего кода. Доказательства из этого файла применимы к локальной проверке
гейта, отдельная приёмка ВМ использует реальные client endpoints.
