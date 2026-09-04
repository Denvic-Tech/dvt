import json
from typing import List

from src.logger import logger
from src.node_dsl import PrimitiveBaseNode, InputField, node_typing, OutputField


class CreateList(PrimitiveBaseNode):
    TITLE = "Create List"
    CATEGORY = "Primitive"
    DISABLED = True

    # Используем **kwargs или JSON строку
    json_string: str = InputField(default="[]", multiline=True)

    output: List[node_typing.IO.PRIMITIVE] = OutputField()

    def process(self):
        try:
            result = json.loads(self.json_string)
            if not isinstance(result, list):
                raise ValueError("Input JSON must be an array (list).")
            self.output = result
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON string for list: {e}")
            raise ValueError(f"Invalid JSON string: {e}")
