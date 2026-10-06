# Native REST API метаданных DVT

[Головной план](MAIN_PLAN.ru.md), [draft OpenAPI](openapi.draft.yaml). Это проект API, не реализация. База `/api/v1/catalog`; модель OpenMetadata знакома клиентам, но идентичность DTO/SDK-совместимость не обещаются.

## Соглашения

UUID key, stable name/FQN, редактируемый displayName; entity references и коллекции glossaries/glossaryTerms/domains/tags/classifications. FQN escaping документировать, не split по точке. dataframes представляют порты, columns — occurrences устойчивого field ID. Typed schema и business annotations разделены, table description не помещается в фиктивное поле.

Списки `{data,paging:{before,after,total}}`, limit default25/max100, fields/q; курсор связан с фильтром/снимком, before/after взаимоисключающие. total только доступных сущностей. PATCH application/json-patch+json, whitelist add/replace/remove/test и If-Match; missing428/stale412. JSON Patch remove свойства override = UNSET, null = CLEAR. DELETE patch возвращает всё наследование. REST-write с Idempotency-Key; тот же ключ/другой payload =409. Project/shared/runtime права раздельны; source мета не становится пользовательской правкой автоматически.

## Методы

| Ресурс | Операции |
|---|---|
| glossaries/glossaryTerms/domains/classifications/tags | GET/POST списка, GET/PATCH карточки, GET name lookup; минимальные справочники |
| glossaryTerms/{id}/usage, domains/{id}/usage | GET доступной области влияния |
| dataframes/columns/отдельного поля | GET структуры/разрешённой меты/provenance |
| annotationOverrides | GET/POST; GET/PATCH/DELETE по id |
| projects/{projectId}/gaps | GET дедуплицированной очереди |
| schemaObservations | POST runtime/source schema/annotations |
| metadataCapabilities?connectionId=... | GET возможностей конкретного source/target connection |
| metadataChanges/preview, metadataChanges | POST preview и atomic modal Save |
| dataframes/{id}/lineage, schemaChanges | GET на этапе 2 |
| dataframes/{id}/versions/{snapshotId} | GET технического снимка, не governance history UI |

Soft delete справочников разрешён только неиспользуемым сущностям. Нет сложного lifecycle/restore/batch API. Runtime observations не запускают проект для просмотра и не выполняют полный dataframe compute.

Source observations содержат scoped locator/local IDs/source version, typed fields, stream/field annotations, evidence и mapping. Limits/version validation исключают malformed/oversized payload. Совпадение чужого UUID/имени не связывает независимые источники. Write capabilities/report также доступны в meta результате ноды: status/unsupported properties/warnings и результаты данных/меты различаются. Metadata-only retry не повторяет data write.

## Атомарный Save

Preview принимает target dataframe/field, expected graph/schema/annotation revisions, term/domain drafts, dirty changes. SET(reference/value), CLEAR и UNSET явны; omitted = «не менять». Draft refs id/clientId; реальные UUID подставляются внутри транзакции.

Preview возвращает доступные occurrences, protected overrides, warnings и previewToken. Shared mutation требует отдельного права; hidden usage не раскрывает чужие проекты. Token не является авторизацией; Save повторно проверяет права/версии.

Save принимает previewToken и Idempotency-Key: одна транзакция создаёт/правит term/domain и локальный patch, сохраняет catalog revision. Ошибка не оставляет случайный термин; конфликт409 сохраняет клиентский draft. Ответ clientIdMap/revisions/effective annotations. Cancel и «Применить к черновику» не выполняют writes.

## Контракты и границы

Python SDK этапа 2 использует scoped runtime metadata context, не произвольные HTTP writes. Public schemas/SDK стабилизируются в этапе 3. Draft может описывать будущие native методы, но релизная OpenAPI содержит только реализованные.

Avro/OpenMetadata/Iceberg adapters/export endpoints, OpenMetadata push и `/api/openmetadata/v1` facade исключены из ТЗ. Будущие интеграции ядра используют native typed snapshot/public contracts.

Ориентиры familiar model: [OpenMetadata resources](https://github.com/open-metadata/OpenMetadata/blob/main/DEVELOPER.md), [Table](https://github.com/open-metadata/OpenMetadata/blob/1.12.0-release/openmetadata-spec/src/main/resources/json/schema/entity/data/table.json), [TagLabel](https://github.com/open-metadata/OpenMetadata/blob/1.12.0-release/openmetadata-spec/src/main/resources/json/schema/type/tagLabel.json). Собственные DVT поля source/provenance/typed schema явно документированы; стандартный внешний Column их не заменяет.
