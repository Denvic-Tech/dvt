# ТЗ: метаданные потоков DVT

Актуальный план на три этапа. Заменяет прежний governance и этап внешних интеграций. Исполняемый backend не менялся. При расхождении этот документ и задания этапов определяют объём работ.

| Этап | Результат | Задание |
|---|---|---|
| 1. MVP | UI, сохранение и базовое наследование; чтение меты БД/Parquet/Битрикс24 и запись меты БД/Parquet | [STAGE_01_MVP_IO.ru.md](STAGE_01_MVP_IO.ru.md) |
| 2. Происхождение и Python | Rename/derived/merge и публичные методы работы с метой из Execute Python | [STAGE_02_LINEAGE.ru.md](STAGE_02_LINEAGE.ru.md) |
| 3. Публичные контракты | Стабильная модель/SDK/REST для расширений и внешних клиентов | [STAGE_03_EXTENSION_API.ru.md](STAGE_03_EXTENSION_API.ru.md) |

## Обязательная модель уже в MVP

1. Устойчивый ID поля независимо от имени/позиции, отдельный occurrence в порту.
2. Дерево primitive/struct/list/map, идентичность вложенных полей/элементов/ключей/значений.
3. Точные параметры типов: ширина/знаковость исходного числа, precision/scale decimal, fixed length, единицы времени, timezone semantics. Неизвестные параметры явны.
4. Required/optional на каждом уровне отдельно от способности pandas dtype хранить пропуски.
5. Default отсутствует и явно задан null различаются. Default не означает автоматическое заполнение данных.
6. Структура и бизнес-аннотации разделены: термин/домен/теги/описание не меняют физический тип.
7. Версионный разрешённый snapshot — единый источник UI/runtime/будущих адаптеров; запуск фиксирует версии.

Принято пользователем как обязательное. Вложенность и параметры сохраняются roundtrip; сложные типы можно показывать компактно/read-only, но нельзя заменять их одной строкой dtype. UUID происхождения не подменяется числовым ID возможной будущей внешней таблицы.

Default и scalar annotations сериализуются без потери decimal/date/time/binary через документированный JSON value codec (например, type-tagged значения). Не передавать произвольные Python объекты; способ кодирования одинаков в REST, source envelope и SDK. Выбор конкретного codec фиксируется до первого writer.

## Границы

Big governance исключён: нет workflow согласований, массовой правки, развитого history/restore UI, taxonomy портала или отдельного поискового кластера. Project access, атомарность, concurrency и технические snapshots остаются обязательными.

Avro/Confluent, OpenMetadata и Iceberg — ориентиры будущих расширений над typed метой, **вне ТЗ**. Нет exports, registry integration, OpenMetadata push/facade, Iceberg writer или SDK compatibility promise. Parquet metadata read/write входит в MVP самостоятельно и не означает Iceberg.

Native API следует модели OpenMetadata: UUID/FQN, ресурсы glossaryTerms/domains/tags, entity references, pagination и JSON Patch. Это DVT API, техническая схема доступна отдельным typed DTO; имитация сервера OpenMetadata не нужна. Не добавлять обязательных сервисов/контейнеров.

## Расширения DVT

Изучены builder README/skill/references, DVT Extension API metadata/gateway, manifest/runtime и UI host. Builder позволяет backend/UI упаковку, APIRouter и объявление миграций; в изученном public host не обнаружен sidebar slot каталога или глобальный catalog resolver. Поле migrations само по себе не доказывает безопасный installed lifecycle.

Ядро остаётся в src/modules/data_catalog; UI — в отдельном dvt-ui. Переиспользовать дисциплину builder: узкие вертикальные сценарии, публичные границы, ленивое получение схем и проверку непустых миграций/installed artifacts. Не копировать private builder/licensing/Cython в DVT.

На этапе 3 предоставить snapshot/source/writer contracts через dvt_extension_api и native REST. Producer/consumer расширения не импортируют src/core напрямую. Поддержка Битрикс24 нужна уже в MVP: при нехватке публичного source contract добавить минимальный контракт сразу, стабильный общий SDK довести в этапе 3. Отключение расширения не уничтожает snapshots и IDs.

Будущий Avro adapter проверяет допустимые типы; OpenMetadata consumer читает familiar REST/model; Iceberg adapter связывает DVT UUID с table UUID/field integer IDs и выполняет table commit. Ни один из этих adapters здесь не реализуется. Упаковка .dvtx и коммерческая защита — отдельное задание.

## Материалы и приёмка

[Модель](DATA_CATALOG_PROPOSAL.ru.md), [native REST](REST_CONTRACT.ru.md), [draft OpenAPI](openapi.draft.yaml), [HTML](dvt-catalog-modal.html). Все задания — *.ru.md; HTML/YAML сохраняют свои форматы. Draft уточняется по этапам, опубликованная OpenAPI содержит только реализованные endpoints.

Каждый этап включает backend/UI/contracts/tests и демонстрацию на dev. MVP считается готовым после реального metadata roundtrip через источники и приёмники; не после одного mock UI. Сроки оценить после проверки producer contracts и dialect capability matrix.
