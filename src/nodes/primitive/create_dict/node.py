import json
from typing import Dict, Any

from src.logger import logger
from src.node_dsl import PrimitiveBaseNode, InputField, OutputField


class CreateDict(PrimitiveBaseNode):
    TITLE = "Create Dictionary"
    CATEGORY = "Primitive"
    DISABLED = True

    # Используем **kwargs для динамического создания словаря
    # В UI это может потребовать специального виджета или динамических входов
    # Пока реализуем через JSON строку
    json_string: str = InputField(default="{}", multiline=True)

    output: Dict[str, Any] = OutputField()

    def process(self):
        try:
            result = json.loads(self.json_string)
            if not isinstance(result, dict):
                raise ValueError("Input JSON must be an object (dictionary).")
            self.output = result
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON string for dictionary: {e}")
            raise ValueError(f"Invalid JSON string: {e}")
