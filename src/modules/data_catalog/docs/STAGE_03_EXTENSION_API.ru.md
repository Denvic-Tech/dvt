# Этап 3. Стабильные контракты меты для расширений

После [этапа 2](STAGE_02_LINEAGE.ru.md). Результат — самостоятельные клиенты могут читать/менять мету через публичные versioned contracts без внутренних импортов DVT.

## Работы

1. Versioned JSON schemas SchemaTree/ResolvedSnapshot/Annotations/SourceMetadata/MetadataWriteReport; policy совместимости minor/major, limits и unknown version handling. Сохранность точных nested types/required/default/provenance обязательна.
2. Public dvt_extension_api facade: получение snapshot, source metadata declaration, lineage, разрешённый runtime patch, capabilities/report. Не отдавать ORM/DB sessions/core objects. Временный узкий Bitrix24 contract MVP довести до стабильного source API.
3. Native REST закрепить: UUID/FQN/references, fields/cursors/JSON Patch, errors/auth/revisions/idempotency. Это familiar OpenMetadata-style API, не совместимый сервер OpenMetadata. Нет отправки туда, facade или требования его SDK.
4. Примеры независимых Python/HTTP clients, contract fixtures и проверка source через действующий Bitrix24 extension. Shared glossary writes и runtime annotations имеют разные права/scope.
5. При потребности нового ExtensionHost slot — сначала согласовать публичную capability; не monkey-patch ядро и не построить общий plugin framework заранее. Каталог не зависит от включения адаптера.

## UI и приёмка

UI показывает capabilities/write report и подробности ошибки, сохраняя простой просмотр/модальное редактирование. Governance/history portal не добавляется.

- SDK и REST читают один и тот же typed snapshot без потерь. Python методы этапа 2 сохраняют совместимость.
- Producer не правит чужой проект и не внедряет исполнение; version/size/unknown metadata ошибки явны.
- Отключение extension не повреждает snapshots, IDs и базовые чтение/запись.
- Public examples без src/core imports/secrets. Проверены реальные runtime/extension boundaries и schema fixtures.

## Вне ТЗ

Avro/Confluent, OpenMetadata и Iceberg adapters могут быть разработаны как расширения над этой метой впоследствии. Здесь нет export endpoints, mapper implementations, OpenMetadata push, schema registration, Iceberg commit и .dvtx commercial/native/licensing поставки.
