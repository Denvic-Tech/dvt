import json
from datetime import datetime, date
from typing import List, Dict, Any

from dateutil import parser

from core.types import DataType
from src.models.queue_topic import QueueTopicRecord


def serialize_for_redis(value: Any) -> str:
    """Преобразует любое значение в строку для Redis."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float, str)):
        return str(value)
    return str(value)


def validate_data_against_schema(
        data: List[Dict[str, Any]],
        topic: QueueTopicRecord
) -> List[Dict[str, Any]]:
    """
    Проверка соответствия ключей и типов + сериализация для Redis.
    """

    # Словарь колонок для быстрого доступа
    columns = {col.name: col for col in topic.columns_schema}
    expected_columns = set(columns.keys())

    for i, record in enumerate(data):
        if not isinstance(record, dict):
            raise ValueError(f"Запись {i}: ожидался dict, получен {type(record).__name__}")

        # 1. Проверка набора полей
        actual_columns = set(record.keys())
        if actual_columns != expected_columns:
            missing = expected_columns - actual_columns
            extra = actual_columns - expected_columns
            errors = []
            if missing:
                errors.append(f"отсутствуют: {missing}")
            if extra:
                errors.append(f"лишние: {extra}")
            raise ValueError(f"Запись {i}: {', '.join(errors)}")

        # 2. Проверка NULL constraints и сериализация
        for col_name, column in columns.items():
            value = record[col_name]

            # Проверка NULL
            if value is None:
                if not column.nullable:
                    raise ValueError(
                        f"Запись {i}, колонка '{col_name}': NULL не допускается"
                    )
                # Сериализуем None
                record[col_name] = serialize_for_redis(value)
                continue

            # 3. Проверка типов И сериализация
            if column.dtype == DataType.DATETIME:
                if isinstance(value, str):
                    try:
                        parser.parse(value)
                        # Сериализуем дату
                        record[col_name] = serialize_for_redis(value)
                        continue
                    except (ValueError, TypeError):
                        raise ValueError(
                            f"Запись {i}, колонка '{col_name}': "
                            f"ожидался DATETIME, получена строка не являющаяся датой: '{value}'"
                        )
                elif isinstance(value, (datetime, date)):
                    # Сериализуем datetime/date объект
                    record[col_name] = serialize_for_redis(value.isoformat())
                    continue
                else:
                    raise ValueError(
                        f"Запись {i}, колонка '{col_name}': "
                        f"ожидался DATETIME, получен {type(value).__name__}"
                    )
            else:
                actual_type = DataType.from_type(type(value))
                expected_type = column.dtype

                if actual_type != expected_type:
                    # Проверяем допустимые нестрогие соответствия
                    if (expected_type == DataType.FLOAT and actual_type == DataType.INT) or \
                            (expected_type == DataType.STRING and actual_type in [DataType.INT, DataType.FLOAT,
                                                                                  DataType.BOOLEAN]) or \
                            (expected_type == DataType.BOOLEAN and actual_type in [DataType.INT, DataType.STRING]):
                        # Сериализуем с преобразованием типа
                        record[col_name] = serialize_for_redis(value)
                        continue

                    raise ValueError(
                        f"Запись {i}, колонка '{col_name}': "
                        f"ожидался {expected_type.value}, получен {actual_type.value}"
                    )

                # Тип совпадает - просто сериализуем
                record[col_name] = serialize_for_redis(value)

    return data
