import json
from pathlib import Path
from functools import lru_cache
from typing import Dict, Any, Optional, List

from src.logger import logger
import config


class LocalizationManager:
    """
    Управляет загрузкой и доступом к данным локализации для нод.
    """

    def __init__(self, locales_dir: Path):
        self.locales_dir = locales_dir
        # Структура: lang_code -> {"nodes": {...}, "type_mapping": {...}}
        self.loaded_locales: Dict[str, Dict[str, Any]] = {}
        self._load_all_locales()

    def _load_all_locales(self) -> None:
        """
        Загружает все файлы локализации из указанной директории.
        Ожидаемая структура: locales_dir/{lang_code}/nodes.json
        Внутри nodes.json: {"nodes": { "NodeName": { ... } }, "type_mapping": { "TYPE": "ТИП" }}
        """
        if not self.locales_dir.is_dir():
            logger.warning(f"Директория локалей не найдена: {self.locales_dir}")
            return

        for lang_dir in self.locales_dir.iterdir():
            if lang_dir.is_dir():
                lang_code = lang_dir.name
                nodes_file = lang_dir / "nodes.json"
                if nodes_file.is_file():
                    try:
                        with open(nodes_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            self.loaded_locales[lang_code] = {
                                "nodes": data.get("nodes", {}),
                                "type_mapping": data.get("type_mapping", {})
                            }
                        logger.info(f"Загружены локализации для языка '{lang_code}' из {nodes_file}")

                    except json.JSONDecodeError:

                        logger.error(f"Ошибка декодирования JSON в файле: {nodes_file}")

                    except Exception as e:
                        logger.error(f"Не удалось загрузить файл локализации {nodes_file}: {e}")
                else:
                    logger.debug(f"Файл nodes.json не найден для языка '{lang_code}' в {lang_dir}")

        if not self.loaded_locales:
            logger.info("Локализации не загружены. Будут использоваться значения по умолчанию.")

    def get_available_languages(self) -> List[str]:
        """Возвращает список кодов доступных языков."""
        return list(self.loaded_locales.keys())

    def get_translation(self, lang: str, node_class_name: str, key: str, default_value: Any = None) -> Any:
        """
        Получает перевод для атрибута ноды (например, "display_name", "description").
        Ключ "TITLE" из старого формата теперь соответствует "display_name".
        Ключ "CATEGORY" не поддерживается в новом формате JSON.
        """
        lang_data = self.loaded_locales.get(lang)
        if not lang_data:
            return default_value

        node_translations_map = lang_data.get("nodes")
        if not node_translations_map:
            return default_value

        node_data = node_translations_map.get(node_class_name)
        if not node_data:
            return default_value

        return node_data.get(key, default_value)

    def get_field_translation(
            self,
            lang: str,
            node_class_name: str,
            definition_group_key: str,  # "input_definitions" или "output_definitions"
            attr_name: str,  # Имя атрибута Python (ключ для поиска поля в JSON)
            translation_key: str,  # "name", "description" (tooltip не поддерживается в новом JSON)
            default_value: Any = None
    ) -> Any:
        """
        Получает перевод для атрибута поля (name, description).
        """
        lang_data = self.loaded_locales.get(lang)
        if not lang_data:
            return default_value

        node_translations_map = lang_data.get("nodes")
        if not node_translations_map:
            return default_value

        node_data = node_translations_map.get(node_class_name)
        if not node_data:
            return default_value

        definitions_group = node_data.get(definition_group_key)
        if not definitions_group:
            return default_value

        field_translations = definitions_group.get(attr_name)
        if not field_translations:
            return default_value

        return field_translations.get(translation_key, default_value)

    def get_type_translation(
            self,
            lang: str,
            type_key: str,
            default_value: Optional[str] = None
    ) -> str:
        """
        Получает перевод для системного типа данных из "type_mapping".
        Возвращает type_key или default_value, если перевод не найден.
        """
        lang_data = self.loaded_locales.get(lang)
        if not lang_data:
            return default_value if default_value is not None else type_key

        type_mapping = lang_data.get("type_mapping")
        if not type_mapping:
            return default_value if default_value is not None else type_key

        return type_mapping.get(type_key, default_value if default_value is not None else type_key)


@lru_cache(maxsize=1)
def get_localization_manager() -> Optional[LocalizationManager]:
    return LocalizationManager(config.PROJECT.LOCALES_DIR)
