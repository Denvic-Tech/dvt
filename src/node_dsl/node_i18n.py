from typing import Any, Dict, List, Type, TypeVar
from pydantic import BaseModel


T = TypeVar('T', bound=BaseModel)


def apply_i18n(model: T, loc: Dict[str, Any], type_mapping: Dict[str, str]) -> T:
    """
    Возвращает новую копию Pydantic-модели, где все поля,
    помеченные json_schema_extra={'i18n': True},
    подставлены из loc (mapping по field_name или по attr_name для списков).

    Логика:
    - Простые поля: заменяем model.field на loc[field] если есть.
    - Списки вложенных BaseModel: ожидаем loc[field] как dict {attr_name: sub_loc},
      рекурсивно применяем к каждому элементу.
    """
    cls: Type[T] = model.__class__
    data: dict[str, Any] = {}

    model_fields = cls.model_fields  # type: ignore

    for name, field_info in model_fields.items():
        value = getattr(model, name)
        extra: dict = field_info.json_schema_extra or {}

        if extra.get('i18n', False):
            if name == "display_type":
                display_type = loc.get(name, value)
                if not display_type and hasattr(model, "type"):
                    display_type = type_mapping.get(model.type, value) or model.type

                data[name] = display_type
            else:
                data[name] = loc.get(name, value)

        elif isinstance(value, list) and value and isinstance(value[0], BaseModel):
            sub_mapping = loc.get(name, {}) or {}
            new_list = []
            for item in value:
                # для каждого вложенного BaseModel ищем по attr_name
                sub_loc = sub_mapping.get(item.attr_name, {})
                new_list.append(apply_i18n(item, sub_loc, type_mapping))

            data[name] = new_list

        # Обычные поля
        else:
            data[name] = value

    return cls(**data)
