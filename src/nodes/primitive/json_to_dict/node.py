import json
from typing import Dict

from src.logger import logger
from src.node_dsl import PrimitiveBaseNode, InputField, OutputField


class JsonToDict(PrimitiveBaseNode):
    TITLE = "JSON String to Dict/List"
    CATEGORY = "Primitive"
    DISABLED = True

    json_string: str = InputField(
        agent_description=(
            "Disabled legacy primitive. Supply valid JSON object text for the declared dictionary "
            "output. Despite the title, arrays are rejected. Do not rely on the parser accepting "
            "scalar JSON values, which do not match the output contract."
        ),
        multiline=True,
    )

    output: Dict = OutputField()

    def process(self):
        try:
            output = json.loads(self.json_string)
            if isinstance(output, list):
                raise ValueError("Input JSON must be an object (dictionary).")
            self.output = output
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON string provided: {e}")
            raise ValueError(f"Invalid JSON string: {e}")
