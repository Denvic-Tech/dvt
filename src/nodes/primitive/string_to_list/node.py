from typing import List

from src.node_dsl import PrimitiveBaseNode, InputField, OutputField


class StringToList(PrimitiveBaseNode):
    TITLE = "String to List"
    CATEGORY = "Primitive"
    DISABLED = True

    string: str = InputField(
        agent_description=(
            "Disabled legacy primitive. Provide the string to split into text items; elements are "
            "not parsed as numbers or JSON. Empty input and repeated separators retain empty "
            "items."
        ),
    )
    separator: str = InputField(
        agent_description=(
            "Choose a non-empty literal separator. Python str.split is used, so this is not a "
            "regular expression and no CSV quoting or escaping is recognized."
        ),
        default=",",
    )
    strip_whitespace: bool = InputField(
        agent_description=(
            "Leave true to remove leading and trailing whitespace from each resulting item; use "
            "false when whitespace is meaningful. Empty items are retained in either mode."
        ),
        default=True,
    )  # Удалять ли пробелы по краям

    output: List[str] = OutputField()

    def process(self):
        if self.strip_whitespace:
            self.output = [item.strip() for item in self.string.split(self.separator)]
        else:
            self.output = self.string.split(self.separator)
