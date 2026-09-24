from typing import List

from src.node_dsl import PrimitiveBaseNode, InputField, OutputField


class BoolList(PrimitiveBaseNode):
    TITLE = "String to Boolean List"
    CATEGORY = "Primitive"
    DISABLED = True

    values_string: str = InputField(
        agent_description=(
            "Disabled legacy primitive. Split this string into Boolean tokens: after trimming and "
            "lowercasing, only true, 1, y, yes, and on become true. Every other token, including "
            "an empty or misspelled token, becomes false without validation; inspect values before "
            "using it."
        ),
    )  # Переименовано
    delimiter: str = InputField(
        agent_description=(
            "Use a non-empty literal separator for Python string splitting, not a regular "
            "expression. Leading, trailing, and adjacent separators create empty tokens that "
            "become false."
        ),
        default=",",
    )

    output: List[bool] = OutputField()

    @staticmethod
    def str_to_bool(value: str) -> bool:
        return value.strip().lower() in ("true", "1", "y", "yes", "on")  # Добавлены варианты

    def process(self):
        self.output = [self.str_to_bool(v) for v in self.values_string.split(self.delimiter)]
