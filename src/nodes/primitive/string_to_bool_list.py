from typing import List

from src.node_dsl import PrimitiveBaseNode, InputField, OutputField


class BoolList(PrimitiveBaseNode):
    TITLE = "String to Boolean List"
    CATEGORY = "Primitive"
    DISABLED = True

    values_string: str = InputField()  # Переименовано
    delimiter: str = InputField(default=",")

    output: List[bool] = OutputField()

    @staticmethod
    def str_to_bool(value: str) -> bool:
        return value.strip().lower() in ("true", "1", "y", "yes", "on")  # Добавлены варианты

    def process(self):
        self.output = [self.str_to_bool(v) for v in self.values_string.split(self.delimiter)]
