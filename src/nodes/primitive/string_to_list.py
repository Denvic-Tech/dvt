from typing import List

from src.node_dsl import PrimitiveBaseNode, InputField, OutputField


class StringToList(PrimitiveBaseNode):
    TITLE = "String to List"
    CATEGORY = "Primitive"
    DISABLED = True

    string: str = InputField()
    separator: str = InputField(default=",")
    strip_whitespace: bool = InputField(default=True)  # Удалять ли пробелы по краям

    output: List[str] = OutputField()

    def process(self):
        if self.strip_whitespace:
            self.output = [item.strip() for item in self.string.split(self.separator)]
        else:
            self.output = self.string.split(self.separator)
