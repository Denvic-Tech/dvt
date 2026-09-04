import threading
from collections import defaultdict
from typing import TYPE_CHECKING

from src.logger import logger
from src.node_dsl.localization import get_localization_manager
from src.node_dsl.variables.system_variables import build_system_variable_definition_payloads
from src.schemas.node_definition import NodeDefinition, SystemVariableDefinitionModel

from ._bootstrap import ensure_bootstrapped, registry_transaction, reset_bootstrap_state
from .categories import resolve_category_color

if TYPE_CHECKING:
    from src.node_dsl.base_node import BaseNode

NODE_DEFINITIONS: dict[str, dict[str, "NodeDefinition"]] = defaultdict(dict)

_REGISTRY_LOCK = threading.RLock()


def _create_node_base_definition(node_cls: type["BaseNode"]) -> "NodeDefinition":
    """
    Создает базовое, нелокализованное определение ноды.
    Используется для инициализации реестра нод.
    """
    input_definitions = {
        field.attr_name: field.get_definition()
        for field in node_cls._input_field_instances.values()
    }
    output_definitions = {
        field.attr_name: field.get_definition()
        for field in node_cls._output_field_instances.values()
    }
    system_variable_definitions = {
        variable_name: SystemVariableDefinitionModel(**payload)
        for variable_name, payload in build_system_variable_definition_payloads(
            getattr(node_cls, "SYSTEM_VARIABLES_MODEL", None)
        ).items()
    }

    return NodeDefinition(
        input_definitions=input_definitions,
        output_definitions=output_definitions,
        system_variable_definitions=system_variable_definitions,
        name=node_cls.__name__,
        emoji=node_cls.EMOJI,
        display_name=node_cls.TITLE or node_cls.__name__,
        description=(node_cls.DESCRIPTION or getattr(node_cls, "__doc__", "") or "").strip(),
        python_module=node_cls.__module__,
        category=node_cls.CATEGORY,
        category_color=resolve_category_color(node_cls.CATEGORY),
        tags=node_cls.TAGS,
        type=node_cls.TYPE,
        output_node=node_cls.OUTPUT_NODE,
        deprecated=node_cls.DEPRECATED,
        experimental=node_cls.EXPERIMENTAL,
        visible=node_cls.VISIBLE
        and node_cls.CATEGORY != "Internal",  # TODO: Определять по cls.TYPE
        additional_schema=node_cls.ADDITIONAL_SCHEMA,
        extension_name=node_cls.EXTENSION_NAME,
        extension_version=node_cls.EXTENSION_VERSION,
    )


def build(node_cls: type["BaseNode"]) -> None:
    with registry_transaction(), _REGISTRY_LOCK:
        if node_cls.__name__ in NODE_DEFINITIONS:
            raise ValueError(f"Node definitions for '{node_cls.__name__}' are already registered.")

        manager = get_localization_manager()
        base_definition: NodeDefinition = _create_node_base_definition(node_cls)

        NODE_DEFINITIONS[node_cls.__name__]["default"] = base_definition.model_copy(deep=True)

        if manager:
            available_languages = manager.get_available_languages()
            if not available_languages:
                logger.debug(
                    f"Для ноды {node_cls.__name__} нет доступных языков для локализации, используется только default."
                )

            for lang_code in available_languages:
                localized_def = base_definition.model_copy(deep=True)

                # Локализация атрибутов самой ноды
                localized_def.display_name = manager.get_translation(
                    lang_code, node_cls.__name__, "display_name", localized_def.display_name
                )
                # "DESCRIPTION" теперь "description" в JSON
                localized_def.description = manager.get_translation(
                    lang_code, node_cls.__name__, "description", localized_def.description
                )
                # "CATEGORY" не локализуется из нового формата JSON, остается значение по умолчанию
                # localized_def.category = manager.get_translation(...)

                # Локализация Input Definitions
                for input_def in localized_def.input_definitions.values():
                    input_def.display_name = manager.get_field_translation(
                        lang_code,
                        node_cls.__name__,
                        "input_definitions",
                        input_def.attr_name,
                        "display_name",
                        input_def.display_name,
                    )
                    if hasattr(input_def, "description"):
                        input_def.description = manager.get_field_translation(
                            lang_code,
                            node_cls.__name__,
                            "input_definitions",
                            input_def.attr_name,
                            "description",
                            input_def.description,
                        )
                    # tooltip не локализуется из нового формата JSON

                    # Локализация типа данных
                    input_def.display_type = manager.get_type_translation(
                        lang_code, input_def.type, input_def.type
                    )

                # Локализация Output Definitions
                for output_def in localized_def.output_definitions.values():
                    output_def.display_name = manager.get_field_translation(
                        lang_code,
                        node_cls.__name__,
                        "output_definitions",
                        output_def.attr_name,
                        "display_name",
                        output_def.display_name,
                    )
                    if hasattr(output_def, "description"):
                        output_def.description = manager.get_field_translation(
                            lang_code,
                            node_cls.__name__,
                            "output_definitions",
                            output_def.attr_name,
                            "description",
                            output_def.description,
                        )
                    # tooltip не локализуется

                    # Локализация типа данных
                    output_def.display_type = manager.get_type_translation(
                        lang_code, output_def.type, output_def.type
                    )

                NODE_DEFINITIONS[node_cls.__name__][lang_code] = localized_def


def add(node_name: str, definition: "NodeDefinition", lang: str = "default") -> None:
    with registry_transaction(), _REGISTRY_LOCK:
        if lang in NODE_DEFINITIONS.get(node_name, {}):
            raise ValueError(
                f"Node definition for '{node_name}' in language '{lang}' is already registered."
            )
        NODE_DEFINITIONS[node_name][lang] = definition


def get(node_name: str, lang: str = "default") -> "NodeDefinition":
    with registry_transaction(), _REGISTRY_LOCK:
        definitions_by_lang = NODE_DEFINITIONS.get(node_name)

    if not definitions_by_lang:
        ensure_bootstrapped(is_ready=lambda: bool(NODE_DEFINITIONS), force=True)
        with registry_transaction(), _REGISTRY_LOCK:
            definitions_by_lang = NODE_DEFINITIONS.get(node_name)

    with registry_transaction(), _REGISTRY_LOCK:
        if not definitions_by_lang:
            raise KeyError(f"Node definitions for '{node_name}' are not registered.")

        definition = definitions_by_lang.get(lang)
        if not definition:
            logger.warning(
                f"Definition for node '{node_name}' in language '{lang}' not found. Falling back to 'default'."
            )
            definition = definitions_by_lang.get("default")

            if not definition:
                raise KeyError(f"Default definition for node '{node_name}' is not registered.")

        return definition.model_copy(deep=True)


def get_all(lang: str = "default") -> dict[str, "NodeDefinition"]:
    ensure_bootstrapped(is_ready=lambda: bool(NODE_DEFINITIONS))
    with registry_transaction():
        with _REGISTRY_LOCK:
            names = list(NODE_DEFINITIONS.keys())
        return {name: get(name, lang) for name in names}


def clear() -> None:
    with registry_transaction(), _REGISTRY_LOCK:
        NODE_DEFINITIONS.clear()
    reset_bootstrap_state()
