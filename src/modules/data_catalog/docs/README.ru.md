# Метаданные потоков DVT

Начинать с [головного ТЗ](MAIN_PLAN.ru.md).

- [Этап 1: MVP с UI и metadata read/write](STAGE_01_MVP_IO.ru.md).
- [Этап 2: происхождение и Execute Python](STAGE_02_LINEAGE.ru.md).
- [Этап 3: public contracts расширений](STAGE_03_EXTENSION_API.ru.md).
- [Модель](DATA_CATALOG_PROPOSAL.ru.md), [native REST](REST_CONTRACT.ru.md), [draft OpenAPI](openapi.draft.yaml).
- [HTML просмотра](dvt-catalog-view.html), [HTML modal](dvt-catalog-modal.html), [тексты UI](real-project-developer-notes.ru.md).

Avro/OpenMetadata/Iceberg adapters, OpenMetadata push/facade и большой governance вне ТЗ. REST модель familiar OpenMetadata-style, совместимость SDK не обещается. Точная typed схема/IDs/default/required/snapshot обязательны с MVP. БД/Parquet metadata read/write и чтение producer меты Битрикс24 входят в MVP.

HTML — локальные прототипы по проекту из 17 нод/20 связей, разметка предложенная; правки в памяти, сервер не вызывается. Новые source/target UI states в макетах ещё не показаны. Draft — будущий контракт, не существующие методы. Исполняемая реализация не изменена. Проверки документации/ссылок/refs не заменяют runtime/SDK/read-write интеграционные tests.
