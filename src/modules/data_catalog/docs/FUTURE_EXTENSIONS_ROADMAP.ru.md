# Roadmap будущих расширений метаданных DVT

## Статус и обязательность

Это архитектурный roadmap, а не дополнительные функции текущего MVP. Avro/Confluent, OpenMetadata и Iceberg реализуются отдельными будущими заданиями над ядром меты. Отправка в OpenMetadata не требуется и не включена в roadmap как обязательная функция. Конкретные версии, сроки, лицензирование и формат поставки расширений здесь не утверждаются.

**Разработчику и его ИИ:** до изменения модели, хранения, API или SDK прочитать [головное ТЗ](MAIN_PLAN.ru.md) и этот документ. Сохранить возможности из таблиц ниже уже в MVP. Не упрощать обязательную мету из-за того, что внешняя интеграция пока не реализуется. Если решение теряет точность, вложенность, идентичность или происхождение, описать потерю и согласовать изменение требований до реализации.

## Очереди roadmap

| Очередь | Что выполняется | Результат |
|---|---|---|
| Сейчас: этап 1 ядра | Полная typed-модель, IDs, snapshots, source/target metadata, UI | Метаданные сохраняются без потерь и доступны независимо от внешних платформ |
| Сейчас: этап 2 ядра | Confirmed lineage и Execute Python metadata facade | Сложные преобразования не теряют смысл и идентичность полей |
| Сейчас: этап 3 ядра | Стабильные public JSON/REST/SDK contracts | Расширения могут работать со snapshot без внутренних src/core imports |
| Будущее A: Avro / Confluent | Отдельный adapter typed snapshot → Avro schema и профиль аннотаций | Переносимый документ; registry registration и Kafka serializers только по отдельному запросу |
| Будущее B: OpenMetadata ecosystem | Независимые клиенты/расширения используют familiar native REST; при запросе — явный mapping документов | DVT встраивается через знакомые resource/reference/pagination/PATCH подходы; push и серверная имитация OpenMetadata не обязательны |
| Будущее C: Iceberg на S3 / Parquet | Отдельный table writer/adapter с catalog binding, schema evolution и commit | Полноценная Iceberg-таблица, а не просто папка Parquet |

A/B/C — направления, не жёсткая последовательность релизов. Любое запускается после готовности нужного публичного контракта. Не заставлять Iceberg ждать Avro registry integration или внедрения OpenMetadata.

## Что сохранять сейчас для каждого направления

| Направление | Что должно быть в ядре с MVP | Что нельзя делать |
|---|---|---|
| Avro / Confluent | Точное дерево типов, required/unknown, explicit default presence, logical parameters, технические имена отдельно от business synonyms, JSON value codec | Считать arbitrary map/unknown/union всегда экспортируемыми; заменять неподдержанный тип string; терять absent/default-null |
| OpenMetadata | UUID/FQN, stable technical name и displayName, refs терминов/доменов/тегов, versioned native DTO, pagination/PATCH/errors/access | Обещать SDK compatibility по сходству URL; урезать typed схему до внешнего Column; смешивать classification tags и glossary terms |
| Iceberg / Parquet | Независимые DVT field IDs, вложенные IDs, precise decimals/timezone, required и schema revisions, подтверждённый rename/derived lineage | Назначать IDs по порядку/имени; называть обычный Parquet dataset Iceberg; подменять DVT UUID внешним field integer ID |
| Все направления | Структура отдельно от annotations, immutable resolved snapshot, source provenance, lossless portable envelope, explicit unsupported report | Мутировать общий snapshot в adapter; хранить copies пользовательских patches на каждом шаге; терять foreign metadata keys |

## Avro: граница будущего расширения

Adapter получает typed snapshot, преобразует допустимые типы и annotations в документ выбранного профиля. Технические aliases и синонимы бизнес-термина различаются; arbitrary metadata требует JSON validation. Roundtrip проверяется по исходному документу, а не только по нормализованному fingerprint, который может исключать аннотации.

Проверки будущего задания: decimal precision/scale, nullable/default, nested structures, имена/aliases, поддержанные maps и temporal semantics, явные ошибки unsupported. Создание схемы не доказывает Kafka wire compatibility. API registry и serializers — отдельная потребность, не скрытая зависимость ядра.

## OpenMetadata: граница будущих клиентов

Наш REST уже ориентирован на знакомую модель. Собственные typed/source/provenance поля DVT явно описаны; стандартные OpenMetadata DTO не объявляются достаточными для всей меты. Версия external mapping закрепляется только при разработке конкретного расширения.

Future consumer может читать DVT без установки OpenMetadata. Если нужен document mapping, schema fields/terms/classifications/domains переводятся явно, ограничения per-field domain и provenance отражаются в отчёте. Отправка в OpenMetadata, bidirectional sync и /api/openmetadata/v1 facade не являются текущими требованиями.

## Iceberg: граница будущего writer

Нужен binding `(DVT field ID) ↔ (Iceberg table UUID, Iceberg field ID)`, включая вложенные элементы. Числовые IDs назначаются/согласуются с целевой таблицей при создании/изменении её схемы; не выводятся из имени/индекса. Rename сохраняет целевой ID только при подтверждённом сохранении поля; новое вычисление под тем же именем не считается прежним полем.

Writer проверяет actual values/types против table schema, Parquet field IDs, partition/sort configuration и поддержанный evolution. Требуются каталог, metadata/manifests/snapshots и корректный table commit. Схема data_catalog не владеет этим lifecycle; политика partitioning не добавляется обязательной к каждому потоку MVP.

Описание переносится в доступную schema doc; термины/домены/теги через профиль properties/sidecar/catalog с явными ограничениями. Не обещать универсальный rich annotations стандарт каждого Parquet reader. Имеющийся MVP envelope сохраняет информацию для такого mapping.

## Архитектурная приёмка текущего ядра

- JSON roundtrip сохраняет nested IDs/types, precision/scale/time semantics, required unknown/false/true и absent/default-null; codec сохраняет decimal/date/time/binary.
- Rename не меняет identity; derived создаёт новую; source foreign IDs scoped, совпадение имени не связывает поля.
- Snapshot фиксирует graph/schema/catalog/source versions; REST, Python и extension facade получают согласованное представление.
- DB/Parquet writers добавляют мету без потери служебных/пользовательских keys и честно сообщают ограничения.
- Foreign integrations можно реализовать через public contracts без чтения внутренних ORM/src/core. Отключение consumer не влияет на ядро.

Эти критерии включаются в review/приёмку текущих этапов. Они проверяются native fixtures, не требуют установки Schema Registry/OpenMetadata/Iceberg или сборки их adapters сейчас.

## Технология расширений

Использовать dvt-extensions-builder и переносимый skill при отдельном задании на extension. Проверять manifest/backend/frontend/dependencies, public API и установленный пакет; не принимать успешную упаковку за успешный metadata mapping. Нужные дополнительные Extension API capabilities сначала согласуются. Builder/private protection code не копируется в ядро.
