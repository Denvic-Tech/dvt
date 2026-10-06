# Этап 3. Стабильные контракты ядра и native API

После [этапа 2](STAGE_02_LINEAGE.ru.md). Результат — штатные ноды, Execute Python и внешние клиенты работают с метой через стабильные версионируемые контракты ядра DVT.

## Работы

1. Versioned JSON schemas SchemaTree/ResolvedSnapshot/Annotations/SourceMetadata/MetadataWriteReport; policy совместимости minor/major, limits и unknown version handling. Сохранность точных nested types/required/default/provenance обязательна.
2. Закрепить контракты ядра для получения snapshot, объявления source metadata и lineage, разрешённого runtime patch, capabilities/report. Domain/flow работают через domain contracts; transport DTO и мапперы находятся в infra. Не отдавать клиентам ORM/DB sessions. Минимальный Bitrix24 source contract MVP довести до стабильного контракта коннектора.
3. Native REST закрепить: UUID/FQN/references, fields/cursors/JSON Patch, errors/auth/revisions/idempotency. Это familiar OpenMetadata-style API. Отправка в OpenMetadata, серверная facade и совместимость с его SDK не требуются.
4. Закрепить Python API ядра для Execute Python и примеры независимых HTTP clients, contract fixtures и проверку источника через коннектор Битрикс24. Shared glossary writes и runtime annotations имеют разные права/scope.
5. Все контракты реализовать внутри штатного backend DVT и существующих runtime/Gateway границ. Недоступность отдельного источника не блокирует просмотр сохранённых snapshots.

## UI и приёмка

UI показывает capabilities/write report и подробности ошибки, сохраняя простой просмотр/модальное редактирование. Governance/history portal не добавляется.

- Python API и REST читают один и тот же typed snapshot без потерь. Методы Execute Python этапа 2 сохраняют совместимость.
- Источник не правит чужой проект; version/size/unknown metadata ошибки явны.
- Недоступность коннектора не повреждает snapshots, IDs и базовые чтение/запись.
- Примеры внешних клиентов используют REST без внутренних импортов и secrets. Проверены реальные границы нод/runtime/Gateway и schema fixtures.

## Вне ТЗ

Avro/Confluent, OpenMetadata и Iceberg остаются направлениями будущего развития ядра по [roadmap](FUTURE_INTEGRATIONS_ROADMAP.ru.md). Здесь нет export endpoints, mapper implementations, OpenMetadata push, schema registration или Iceberg commit.
