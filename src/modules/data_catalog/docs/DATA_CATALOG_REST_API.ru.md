# REST API дата-каталога DVT

Статус: план, не реализованный API. Дополняет [модель и интерфейс](DATA_CATALOG_PROPOSAL.ru.md). Проектирование учитывает создание терминов и доменов на лету в одном модальном окне. HTML остаётся локальным макетом, не вызывает эти методы.

## Подход и уровень совместимости

Базовый путь DVT: `/api/v1/catalog`. Названия коллекций, идентификация UUID/FQN, ссылки на сущности, cursor pagination, выбор дополнительных полей и JSON Patch приближены к OpenMetadata. Это собственный API DVT; совпадение стиля не означает совместимость SDK.

Для обмена предусмотреть отдельную проекцию `/api/openmetadata/v1`. При будущей проверке SDK его host настраивается на `https://dvt-host/api/openmetadata`: добавляемый клиентом `/v1` ведёт к этой проекции. Подмножество контрактов должно соответствовать выбранной закреплённой версии OpenMetadata, без дополнительных DVT-полей в строгих JSON schemas. Ориентир первого прототипа — schemas тега `1.12.0-release`; это базовая версия для проверки, не утверждение о самой новой версии продукта. Если интеграция потребуется с другой версией, профиль и contract tests фиксируются для неё отдельно.

Предлагаемые уровни:

1. MVP: схожие методы и DTO, DVT-расширения явно документированы; импорт/экспорт OpenMetadata-подобных документов.
2. Следующий этап: read-only совместимая проекция для перечисленного подмножества и валидатор по официальным schemas. Проверка реальными SDK отдельно от JSON-валидации.
3. Позже, при необходимости: совместимые мутации справочников и таблиц. До этого неподдерживаемые методы возвращают 405, а не имитируют успешную запись.

OpenMetadata не становится обязательным сервисом DVT. Все use cases выполняются в существующем Gateway и модуле data_catalog. Отдельный поисковый кластер не нужен для MVP.

## Что перенимаем, что расширяем

В OpenMetadata используются коллекции ресурсов, UUID, FQN, CRUD, JSON Patch, `fields` и курсоры `before/after`. Эти соглашения видны в [официальном resource pattern](https://github.com/open-metadata/OpenMetadata/blob/main/DEVELOPER.md) и [EntityResource выбранного тега](https://github.com/open-metadata/OpenMetadata/blob/1.12.0-release/openmetadata-service/src/main/java/org/openmetadata/service/resources/EntityResource.java). Дополнительные методы и семантика ниже — проектное решение DVT.

| Понятие DVT | Близкое понятие OpenMetadata | Решение |
|---|---|---|
| Справочник терминов | glossary / glossaryTerm | Коллекции `glossaries`, `glossaryTerms` |
| Классификация | classification / tag | `classifications`, `tags`, отдельные от терминов |
| Принадлежность | domain | Справочник `domains`; один выбранный домен поля в MVP |
| Поток порта | table с columns | Внутри DVT — `dataframes`; наружу — виртуальная Table-проекция |
| Поле | column | Колонка вложена в Table; устойчивый field ID — расширение DVT |
| Проект и выполнение | pipeline и задачи pipeline | Экспортировать как pipeline, не считать ноду физической таблицей |
| Происхождение | lineage | Отдельное сопоставление; resolver наследования остаётся DVT |
| Patch точки графа | Нет эквивалента нашей семантики | Ресурс `annotationOverrides` |
| Итоговая мета и её источник | Частичное пересечение с аннотациями | `effectiveAnnotations`, `provenance`, `gaps` — расширения DVT |

В [Table schema](https://github.com/open-metadata/OpenMetadata/blob/1.12.0-release/openmetadata-spec/src/main/resources/json/schema/entity/data/table.json) колонка имеет name, displayName, dataType, description, tags; таблица — columns и domains. Не добавлять произвольный `domain` или `businessTerm` внутрь Column, выдавая их за стандарт. Внешнюю связь с термином кодировать как TagLabel с `source: "Glossary"`, классификационный тег — с `source: "Classification"`; конкретные поля сверяются с [TagLabel schema](https://github.com/open-metadata/OpenMetadata/blob/1.12.0-release/openmetadata-spec/src/main/resources/json/schema/type/tagLabel.json). Встроенная семантика labelType не заменяет provenance DVT и его branch resolver.

Если разные поля имеют разные домены, Table.domains может содержать объединение их принадлежностей. Персональная принадлежность колонок передаётся согласованным custom extension/sidecar, а не теряется незаметно. Само по себе OpenMetadata-наследование принадлежности по контейнерам не означает наследование по DAG DVT. Структура домена сверяется с [Domain schema](https://github.com/open-metadata/OpenMetadata/blob/1.12.0-release/openmetadata-spec/src/main/resources/json/schema/entity/domains/domain.json).

## Общие соглашения DVT

- JSON DTO используют camelCase; domain dataclasses могут оставаться snake_case. Результат списка: `{ "data": [...], "paging": { "before": null, "after": "opaque", "total": 42 } }`. `total` — число доступных пользователю элементов по фильтру. Не подсчитывать скрытые сущности.
- `limit` по умолчанию 25, максимум 100; `before` и `after` взаимоисключающие. Курсор включает фильтр, стабильную сортировку и catalog revision; при изменении снимка возвращается 409 `CURSOR_STALE` с предложением начать заново.
- Дополнительные поля выбираются через `fields=tags,domains,provenance`; неизвестные значения — 400. Базовые поля всегда возвращаются. Поиск MVP — `q` на соответствующей коллекции, поиск термина учитывает синонимы. Это расширение DVT, не обещание совместимости с поисковым API OpenMetadata.
- UUID — ключ; `name` — стабильное техническое имя; `displayName` — редактируемая подпись. Создание из UI генерирует техническое имя, проверяет его уникальность в глоссарии/области; редактирование displayName не меняет FQN. Lookup: `/name/{fqn}` с официальным экранированием частей FQN в адаптере, не простым split по точкам.
- GET возвращает ETag; PATCH/DELETE требуют `If-Match`, отсутствие — 428, несовпадение — 412. PATCH: `application/json-patch+json`; разрешён whitelist свойств. Пути с индексами массивов проверяются против версии, чтобы не отредактировать другую колонку после reorder.
- Общий Save модального окна использует отдельный атомарный POST с expected revisions всех затронутых объектов. Ревизии — непрозрачные строки DVT; их не путать с числовой metadata version OpenMetadata.
- POST записи поддерживает `Idempotency-Key`: повтор того же payload пользователем возвращает тот же результат; тот же ключ с другим payload — 409. Срок хранения ключей задаётся настройкой (предложение: 24 часа).
- DELETE справочника — soft delete. Используемый домен/термин не удалять без решения о привязках: 409 `ENTITY_IN_USE`. Hard delete и каскадное удаление не входят в MVP. Поле схемы не удаляется пользовательской правкой меты.
- Ошибка DVT: `{ "code": "REVISION_CONFLICT", "message": "...", "details": [...] }`; Validation — 422, auth — 401/403, отсутствующий или недоступный объект — 404. Адаптер OpenMetadata преобразует errors в контракт выбранной версии. ETag/Idempotency-Key здесь — требования DVT, не утверждение о поддержке OpenMetadata.

## Методы справочников

Все пути таблиц ниже относительны `/api/v1/catalog`.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/glossaries` | Список глоссариев |
| POST | `/glossaries` | Создать глоссарий |
| GET | `/glossaries/{id}` | Карточка |
| PATCH | `/glossaries/{id}` | Имя отображения, описание |
| GET | `/glossaryTerms?glossary={id}&q=...` | Поиск терминов |
| POST | `/glossaryTerms` | Создание вне модального Save |
| GET | `/glossaryTerms/{id}` | Термин, определение, синонимы |
| PATCH | `/glossaryTerms/{id}` | Новая версия общего определения |
| DELETE | `/glossaryTerms/{id}` | Soft delete неиспользуемого термина |
| GET | `/domains?q=...` | Поиск доменов |
| POST | `/domains` | Создать домен отдельно |
| GET | `/domains/{id}` | Карточка |
| PATCH | `/domains/{id}` | Новая версия названия/описания |
| DELETE | `/domains/{id}` | Soft delete неиспользуемого домена |
| GET/POST | `/classifications` | Список/создание классификации |
| GET/PATCH | `/classifications/{id}` | Чтение/правка |
| GET/POST | `/tags` | Поиск/создание меток |
| GET/PATCH/DELETE | `/tags/{id}` | Чтение, правка, soft delete |

Для каждой коллекции добавить GET `/name/{fqn}` и GET `/{id}/versions`, `/{id}/versions/{revision}`. Историческая версия проверяет доступ и не превращается в актуальную автоматически. PUT create-or-update по FQN — следующая очередь для ingestion/адаптера, не требуется кнопке Save. Full replacement через PUT не должен стирать не переданные пользователем поля; его точная семантика определяется профилем, не смешивается с PATCH.

GET `/glossaryTerms/{id}/usage` и `/domains/{id}/usage` — расширения DVT: доступные использования с project/node/port/field, пагинацией и отдельными `occurrenceCount`/`explicitBindingCount`. Унаследованное появление не равно новой сохранённой привязке. Для общего редактора нужна отдельная операция просмотра влияния; при недоступных пользователю привязках ответ обозначает `hasHiddenUsage: true` без раскрытия их содержимого и количества. Возможность общей правки требует самостоятельного права и не выводится из права править одно поле.

## Потоки, поля, наследование

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/dataframes?projectId=...&nodeId=...` | Потоки/порты проекта, schema summary |
| GET | `/dataframes/{id}` | Структурная схема и разрешённая мета |
| GET | `/dataframes/{id}/columns` | Поля текущей схемы, признаки изменения/заполненности |
| GET | `/dataframes/{id}/columns/{fieldId}` | Вхождение поля, итоговая мета и provenance по свойствам |
| GET | `/dataframes/{id}/lineage?upstreamDepth=...&downstreamDepth=...` | Граф происхождения с подтверждённостью связей |
| GET | `/annotationOverrides?dataframeId=...&fieldId=...` | Только сохранённые пользовательские patches |
| POST | `/annotationOverrides` | Создать локальный override |
| GET/PATCH/DELETE | `/annotationOverrides/{id}` | Чтение/изменение/возврат наследования |
| GET | `/projects/{projectId}/gaps` | Дедуплицированная очередь неописанных/конфликтных полей |
| GET | `/dataframes/{id}/schemaChanges?fromRevision=...&toRevision=...` | Сравнение структуры |
| GET | `/dataframes/{id}/versions` | Снимки схем/меты |
| GET | `/dataframes/{id}/versions/{snapshotId}` | Воспроизводимый исторический снимок |
| POST | `/schemaObservations` | Приём наблюдения схемы от runtime/ingestion, не пользовательский Save |
| GET | `/dataframes/{id}/exports/avro` | Разрешённая мета как Avro-документ с dvt.* |
| GET | `/dataframes/{id}/exports/openmetadata` | Проекция выбранного потока, отчёт о потерях |

`dataframeId` обозначает ресурс конкретного порта (project/node/direction/port), `fieldId` — устойчивое происхождение, а occurrence ID связывает поле с этой схемой. Запрос исторического поля требует snapshotId; удалённое текущей схемой поле не подменяется одноимённым новым.

Resolver выдаёт `effectiveAnnotations` и `provenance` для каждого свойства, а не записывает итог на каждую ноду. В DTO отдельно возвращаются structuralStatus, annotationStatus и lineageConfidence. Gaps могут различаться по свойствам; проблема нового поля дедуплицируется по идентичности/точке возникновения, локальные конфликты сохраняются отдельно.

Для patch-ресурса поля лежат в `overrides`. Отсутствующее свойство — UNSET; `/overrides/domain: null` — CLEAR; непустая ссылка — SET. JSON Patch `remove /overrides/domain` возвращает наследование. `remove /overrides` целиком запрещён; DELETE patch удаляет все его overrides. Аналогично term; для tags пустой список — явный пустой набор. Resolver не строится на HTTP-прокси OpenMetadata.

`schemaObservations` требует runtime-права, graph revision и idempotency key наблюдения; мета dtype и структура не должны вычислять полный dataframe в Gateway. Runtime не изменяет бизнес-термины. Endpoint lineage в MVP только читает граф DVT; изменение ребра выполняется существующим API редактора проекта, а не дублируется независимым PUT lineage.

## Save одного модального окна

Два расширения DVT:

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/metadataChanges/preview` | Проверить черновик, права, ревизии и показать влияние без записи |
| POST | `/metadataChanges` | Атомарно сохранить общий термин/домен и override поля |

Payload обеих операций одинаков по смыслу. Черновые объекты идентифицируются `clientId`; сервер подставляет их реальные UUID только внутри транзакции. Поле refs может содержать **либо** id, **либо** clientId. Для обновления существующего справочника используется id + expectedRevision; для создания — clientId + create. Разрешены только перечисленные целевые объекты, это не произвольный batch API Gateway.

Пример создания домена и привязки существующего термина. UUID ниже условные; структура — контракт DVT:

```json
{
  "target": {
    "dataframeId": "11111111-1111-4111-8111-111111111111",
    "fieldId": "22222222-2222-4222-8222-222222222222",
    "expectedGraphRevision": "graph-11",
    "expectedSchemaRevision": "schema-3",
    "expectedAnnotationRevision": "annotation-7"
  },
  "domainDrafts": [
    {
      "clientId": "new-sales-domain",
      "create": {
        "name": "sales",
        "displayName": "Продажи",
        "description": "Данные о продажах и регионах."
      }
    }
  ],
  "termDrafts": [],
  "changes": {
    "domain": {"mode": "SET", "reference": {"clientId": "new-sales-domain"}},
    "term": {
      "mode": "SET",
      "reference": {"id": "33333333-3333-4333-8333-333333333333", "expectedRevision": "term-2"}
    },
    "description": {"mode": "SET", "value": "Регион продажи в этом потоке."}
  }
}
```

В changes не переданные свойства не меняются. `mode: "UNSET"` удаляет свойство из локального override и возвращает наследование; `mode: "CLEAR"` ставит явное отсутствие. GET resolved не используется как DTO записи: иначе клиент случайно сохранит все унаследованные значения. Для Save description compare делать относительно локального patch и dirty-state формы.

Preview возвращает proposed entities, affected occurrences, protected downstream overrides, warnings, permissions и непрозрачный `previewToken` с digest payload и ожидаемых ревизий. Токен не является разрешением: Save повторно проверяет auth и все версии; при изменении влияния/графа возвращает 409 и новый preview, а не сохраняет по устаревшей оценке. Срок жизни токена — 10 минут. Отдельные draft revisions защищают общий термин/домен от чужой параллельной правки.

Save передаёт previewToken и Idempotency-Key. Одна транзакция: проверить ревизии → создать/обновить справочники → записать только изменённые свойства override → сохранить catalog revision/audit → зафиксировать. Ответ 200 содержит `clientIdMap`, новые ревизии, override и актуальную effectiveAnnotations. Повтор Save не создаёт второй термин. Ошибка не оставляет домен без привязки. После commit зависимый кеш инвалидируется по затронутым ссылкам и ветвям; распространение не создаёт пользовательские patches.

Отмена окна вообще не делает write-запроса. «Применить к черновику» остаётся клиентским действием. Общая PATCH glossaryTerm/domain доступна для отдельного редактора справочника; модальный Save не выполняет её заранее.

## OpenMetadata-адаптер

Профиль `/api/openmetadata/v1` первой интеграции: read-only GET коллекций и карточек `glossaries`, `glossaryTerms`, `domains`, `classifications`, `tags`, `tables`, `pipelines`; GET по FQN; согласованное чтение lineage в формате выбранной версии. Поля, cursor и ошибки валидируются по этому профилю. Доступ к данным проверяет тот же DVT user context. SDK authentication нужно проверить отдельно; внутренний bearer DVT не объявляется автоматически токеном OpenMetadata.

Table-проекция требует цепочки service/database/databaseSchema для клиентов, которые её читают. Предусмотреть read-only синтетические контейнеры и их endpoint resources по выбранному контракту либо документировать отсутствие такого SDK-сценария. Пример FQN: service `dvt`, database `project_<uuid>`, schema `node_<uuid>`, table `out_output`; имена стабильные, human names идут в displayName. Вход приёмника экспортируется отдельно или ссылается на producer по явному правилу, не создавая фиктивный второй источник данных.

TagLabel.source=Glossary переносит привязку термина; dataType маппится отдельно от Avro. DVT-passthrough/rename/derived преобразуются в column lineage, unknown не выдаётся за доказанную связь. Дополнительная мета экспортируется только зарегистрированными custom properties или sidecar. Нельзя полагаться на сохранение произвольных ключей строгими клиентами. Физические DB tables экспортируются как реальные assets отдельно от виртуальных потоков.

Совместимый write для columns.description/columns.tags позже может создать override в соответствующей точке DVT. Перед этим определить scope, обработку JSON Patch индексов и правило смены термина. Snapshot export материализует итоговую мету для внешнего каталога, но DVT продолжает хранить лишь исходные аннотации и overrides; внешняя материализация не нарушает требование отсутствия копий внутри пайплайна.

Конфликт или unknown не сглаживать экспортом: в отчёте перечислять unmapped properties, ambiguous lineage и потерю per-field domains. Для бесшумной выгрузки можно разрешить только lossless профиль; иначе требуется явный allowLossy. OpenMetadata REST-проекция и Avro export — разные адаптеры одного разрешённого domain snapshot.

## Реализация по очередям и проверки

1. Определить JSON schemas DTO и OpenAPI native API; glossary/domain/tag CRUD, lookup, pagination, разрешённые patch paths.
2. Добавить чтение потоков, resolver/provenance, gaps и runtime observations без пользовательских side effects.
3. Добавить preview + transactional metadataChanges, concurrency/idempotency, usage и права. Подключить модальный редактор.
4. Добавить экспорт Avro и OpenMetadata; fixture validation по закреплённым schemas.
5. При необходимости — read-only совместимую проекцию и конкретный набор SDK roundtrip тестов. Только прошедшее подмножество объявлять совместимым.

Domain: сущности/политики/contracts. Flow: классы use cases с execute, без ORM/HTTP. Infra: persistence, DTO mappers, валидаторы и адаптеры; не импортирует flow. Gateway composition связывает их. Подключение Gateway routes и изменение схем потребует предусмотренного проектом обновления OpenAPI-клиента; UI реализуется вне services/ui.

Минимальные meaningful tests: branch override/CLEAR/UNSET; term/domain общая правка не меняет поле/соседний patch; атомарный rollback Save; retry с тем же idempotency key; конфликт версии между preview и Save; смена graph/schema до сохранения; невозможность править чужой project; отсутствие утечки usage; корректные before/after; rename/новое одноимённое поле; сохранение старого run snapshot. Compatibility checks — JSON schema fixtures и согласованные операции реального клиента, не только совпадение URL.

Этот документ не меняет API или сервисы. Native контракт оформлен в [draft OpenAPI YAML](openapi.draft.yaml). Это 59 операций DVT; совместимая OpenMetadata-проекция пока не описана как реализуемый стандартный контракт и требует отдельного профиля.
