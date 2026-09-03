import json
from pathlib import Path

from pydantic import BaseModel

from src.node_dsl.node_typing import IO
from src.node_dsl import get_all_definitions

import config


def extract_i18n_fields_as_mapping(model: BaseModel) -> dict:
    """
    Извлекает из NodeDefinition только поля с json_schema_extra={'i18n': True}.
    input_definitions/output_definitions возвращает как mapping по attr_name.
    """
    # Защита: проверяем, что передали именно Pydantic-модель
    if not isinstance(model, BaseModel):
        raise TypeError(f"Expected Pydantic BaseModel, got {type(model)}")

    result: dict[str, any] = {}

    # Берём model_fields из класса, чтобы не было депрецированного доступа
    model_fields = model.__class__.model_fields  # type: ignore

    for name, field_info in model_fields.items():
        # json_schema_extra у FieldInfo доступен сразу
        js_extra = field_info.json_schema_extra or {}
        value = getattr(model, name)

        # 1) Простые переводимые поля
        if js_extra.get("i18n", False):
            result[name] = value

        # 2) Коллекции вложенных моделей (legacy list + current mapping)
        else:
            nested_models: dict[str, BaseModel] = {}
            if isinstance(value, list) and value and isinstance(value[0], BaseModel):
                nested_models = {item.attr_name: item for item in value}
            elif isinstance(value, dict) and value:
                first_value = next(iter(value.values()))
                if isinstance(first_value, BaseModel):
                    nested_models = {
                        attr_name: item
                        for attr_name, item in value.items()
                        if isinstance(item, BaseModel)
                    }

            if nested_models:
                first_model = next(iter(nested_models.values()))
                sub_mapping: dict[str, dict[str, any]] = {}
                item_fields = first_model.__class__.model_fields  # type: ignore

                for attr_name, item in nested_models.items():
                    item_data: dict[str, any] = {}

                    for sub_name, sub_field_info in item_fields.items():
                        sub_js_extra = sub_field_info.json_schema_extra or {}
                        sub_value = getattr(item, sub_name)
                        if sub_js_extra.get("i18n", False):
                            item_data[sub_name] = sub_value

                    sub_mapping[attr_name] = item_data

                result[name] = sub_mapping

    return result


def update_nodes_locales():
    available_locales = ["en", "ru"]
    locales_dir: Path = config.PROJECT.LOCALES_DIR

    if not locales_dir.exists():
        raise FileNotFoundError(f"Locales directory {locales_dir} does not exist.")

    for locale in available_locales:
        locale_dir = locales_dir / locale
        if not locale_dir.exists():
            raise FileNotFoundError(f"Locale directory {locale_dir} does not exist.")

        json_file_path = locale_dir / "nodes.json"

        if json_file_path.exists():
            with open(json_file_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        else:
            existing_data = {}
            print(f"Creating JSON file for locale: {locale}")

        existing_nodes_data = existing_data.setdefault("nodes", {})

        for node_class_name, node_def in get_all_definitions().items():
            # 2) Извлекаем переводы как mapping по attr_name
            i18n_fields = extract_i18n_fields_as_mapping(node_def)
            if not i18n_fields:
                continue

            # 3) Если ноды нет в JSON — просто добавляем
            if node_class_name not in existing_nodes_data:
                existing_nodes_data[node_class_name] = i18n_fields
                print(f"[+] Added new node '{node_class_name}'")
            else:
                # 4) Иначе мёржим с уже существующим словарём
                merge_nodes_i18n_dicts(
                    existing_nodes_data[node_class_name],
                    i18n_fields,
                    path=node_class_name,
                )

        existing_type_mapping = existing_data.get("type_mapping", {})
        # 5) Добавляем типы нод в type_mapping
        fresh_type_mapping = IO.__members__
        for type_name, type_value in fresh_type_mapping.items():
            if type_name not in existing_type_mapping:
                existing_type_mapping[type_name] = type_value.value
                print(f"[+] Added new type '{type_name}'")

        existing_data["type_mapping"] = existing_type_mapping

        # 6) Сохраняем файл
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=4)

        print(f"[✔] Locales updated for {locale} in {json_file_path}")


def merge_nodes_i18n_dicts(existing: dict, new: dict, path: str = '') -> dict:
    """
    Рекурсивный мёрж словарей i18n, без списков.
    Всегда мёржим по ключу, печатаем что добавили или пропустили.
    """
    for key, new_value in new.items():
        current_path = f"{path}.{key}" if path else key

        if key not in existing:
            existing[key] = new_value
            print(f"[+] Added field '{current_path}'")
        else:
            existing_value = existing[key]
            if isinstance(new_value, dict) and isinstance(existing_value, dict):
                merge_nodes_i18n_dicts(existing_value, new_value, path=current_path)
            elif existing_value is None:
                existing[key] = new_value
                print(f"[~] Updated field '{current_path}' (was None)")
            else:
                print(f"[=] Kept existing field '{current_path}'")
    return existing


if __name__ == '__main__':
    update_nodes_locales()
