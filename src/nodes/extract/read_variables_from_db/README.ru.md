# Переменные из БД

Тип ноды: `ReadVariablesFromDB`.

## Назначение и выбор

Получает небольшие скалярные или списочные переменные из БД без загрузки всей таблицы в DataFrame.

## Входы и настройка

Подключите объект БД в `connection`. Режим по умолчанию `mode="manual"` требует непустого `manual_variables`: имя → table_name, column_name, aggregation, необязательные database_name/schema_name. Функции: min/max/count/count_distinct/sum/avg/first/last; first/last требуют order_by_column. Для `mode="sql"` задайте `sql_code`; `sql_variables` настраивает политики колонок результата. Политики: nullable=false, литеральный default, target_dtype и is_list_type=false.

## Результат

`output_variables` содержит типизированные переменные; имена колонок SQL-результата становятся именами переменных. DataFrame на выходе нет.

## Поведение и ограничения

SQL должен вернуть не более одной строки с уникальными непустыми именами колонок; несколько строк запрещены. Отсутствие строки даёт null с применением default/nullable. Default применяется до nullable и отличается от отсутствующего default. Полное выполнение и режим метаданных обращаются к БД. Кеширование отключено. Списочный режим означает список в одном значении, а не сбор нескольких строк результата. Равенство значений order_by для first/last отдельно не разрешается.

## Примеры

При подключённой таблице orders с максимальным id 42 результат `last_id=42`. Для пустой таблицы явный default даёт 0.

Значения параметров, без оболочки MCP patch:

```json
{
  "mode": "manual",
  "manual_variables": {
    "last_id": {
      "table_name": "orders",
      "column_name": "id",
      "aggregation": "max",
      "default": 0,
      "target_dtype": "INT"
    }
  }
}
```

## Типовые ошибки

Слишком много SQL-строк: агрегируйте или осмысленно выберите одну упорядоченную строку. Неизвестные sql_variables: используйте реальные aliases. Ошибка null/типа: проверьте defaults и target_dtype; вход называется sql_code, даже если сообщение говорит sql_query.
