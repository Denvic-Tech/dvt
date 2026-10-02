# Этап 1. MVP с UI и чтением/записью метаданных

Основа: [головное ТЗ](MAIN_PLAN.ru.md). Все семь требований модели обязательны сразу. Результат — сохраняемый каталог, confirmed inheritance и metadata roundtrip реальных нод.

## Ядро

Сохранить совместимость ColumnSchema/TableSchema и нынешних мета-ответов. Добавить typed schema tree с вложенными IDs, precise types, required unknown/true/false и explicit default presence; annotations и source provenance отдельно. Внутренний DDD-lite сохраняется. Не менять SchemaPolicy ради каталога.

Минимальные термин/домен/тег справочники, schema revisions, patches и snapshots. SET/UNSET/CLEAR по каждому свойству, одна запись в точке изменения; confirmed passthrough фильтров и входов sinks. Ветви независимы. Python/SQL без явной карты — unknown. Первое наблюдение — «Первая схема», added/removed/type_changed относительно baseline. Снимок запуска и cache restore сохраняют ссылки на версии. Схема без compute полного dataframe.

## Чтение: обязательно

| Источник | Мета |
|---|---|
| БД | Комментарий таблицы и колонок, отражённые types/required/параметры |
| Parquet | Arrow/Parquet schema, footer key-value, поддержанные field annotations/comments и DVT envelope |
| Битрикс24 extension | Доступные названия/описания/технические типы полей из producer расширения |

Перед реализацией проверить актуальный producer Битрикс24 и публичный транспорт, зафиксировать версии. Интеграция обязательна, но готовность нынешнего producer не подтверждена. Если отсутствует API — узкий согласованный source contract добавить в этом этапе; не копировать бизнес-логику расширения.

Комментарии таблицы и поля хранятся отдельно. Source description не создаёт термин автоматически и не меняет физический тип. Обновление источника не затирает user override; исходные значения/source revision сохраняются. Table description должна быть в stream annotations, а не фиктивной колонке.

Свободный комментарий сохраняется как текст. Structured DVT block узнаётся по versioned namespace; чужой JSON не исполняется и не присоединяет foreign UUID автоматически к локальному glossary. Source IDs scoped к producer/locator; разное происхождение не объединяется по имени.

Parquet: дополнить текущие logical schema/partition/pandas/Arrow metadata, не заменять их. Задать supported comment-key conventions вместо обещания универсального комментария Parquet. Для dataset проверять согласованность доступной меты файлов/manifest; не выбирать случайный первый файл. При конфликте — явный report. Logical partition columns сохраняются независимо от отсутствия в физическом файле.

## Запись: обязательно

1. БД: comments таблицы и колонок на штатных writers; фактический source→target mapping. Writer v4 не создаёт таблицу ради комментария. Указать capability matrix поддержанных dialects/drivers и permissions.
2. Parquet: resolved snapshot и versioned envelope с field mapping в footer/schema metadata каждого нового файла; single/dataset/partitioned/append режимы проверяются отдельно. Не обещать переписывание старых файлов при append.
3. Человеческое описание — доступный стандартный comment, термин/домен/теги/схема — DVT block там, где поддержаны capacity и driver. Foreign keys/пользовательский текст сохраняются; явная policy разрешает замену description. Не обрезать block молча.
4. JSON envelope без secrets, executable payload и приватных connection details. Повторное чтение восстанавливает annotations через scoped mapping. Roundtrip с rich метой обязателен в выбранном поддержанном профиле; ограничения других целей отражены явно.
5. Read/write capabilities и report: metadata mode best_effort с warning либо require_metadata с предварительной проверкой. Отсутствие driver capability не является успехом no-op. На старте закрепить обязательные dialects, ограничения коннектора не превращают всю функцию в необязательную.

Референсная integration приёмка: PostgreSQL table/column comments и PyArrow Parquet. Уже поддержанные комментарии других dialects не должны регрессировать; дополнительные dialects включать в capability matrix после подтверждения драйвером. Это минимальный проверяемый baseline, не универсальная гарантия всех БД.
6. Если данные записаны, а comments нет, report различает результаты. Не обещать atomic data+comments всех СУБД; metadata-only retry не повторяет неидемпотентную запись данных. Append конфликт аннотаций имеет определённую policy, не last-file-wins.

Adapters у владельцев нод, resolver/contracts в data_catalog. При изменении нод обновить английский/русский README. Не создавать новый обязательный контейнер.

## UI и API

Панель read-only: несколько нод, последовательные поля, typed summary/annotations/provenance и gaps. Отдельный modal с поиском/созданием/правкой терминов/доменов, локальным описанием и тегами. Общий atomic Save, Cancel отбрасывает всё. CLEAR снимает привязку, UNSET возвращает наследование. Ошибка/conflict не уничтожает черновик; source/target metadata report видим в редакторе соответствующей ноды. UI — dvt-ui, не services/ui.

Native REST в модели OpenMetadata: read/search/create справочников и usage, dataframes/columns/overrides/gaps, schema observations, preview/Save, capabilities. Нельзя сохранять resolved DTO как patch всех свойств; только dirty local values. Project/shared/runtime permissions проверяются раздельно.

## Приёмка

- Мета из БД, Parquet и Битрикс24 видна с source provenance; перечитывание не затирает local override.
- БД→фильтр→Parquet→чтение и Parquet→БД→чтение сохраняют table/field descriptions и rich envelope в поддержанном профиле; nested/partition/pandas/unknown keys не теряются.
- На 01 описание задано один раз, confirmed downstream его читают; override на 03 не меняет соседние ветви. New field создаёт одну задачу; unknown видим.
- Default absent/null и required unknown/optional различаются после roundtrip. Cancel не создаёт сущности; concurrent Save/retry/rollback проверены.
- Malformed/oversized envelope, permissions, unsupported comments и append conflict дают честный статус; retry не дублирует данные.
- Domain/transaction tests, read-write integration, UI e2e и migration непустой БД; старые TableSchema/SchemaPolicy consumers совместимы.

Вне этапа: внешние adapters/exports, Iceberg, registry, OpenMetadata push/facade, big governance, Python metadata SDK. JSON схемы и snapshots не откладываются.
