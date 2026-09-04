from src.logger import logger
from src.node_dsl import TestingBaseNode, InputField, OutputField
from src.node_dsl.hooks import on_validation
from src.node_dsl.exceptions import NodeValidationError
from src.node_dsl.node_typing import IO


class ValidationErrorNode(TestingBaseNode):
    TITLE = "Validation Error Node"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    @on_validation
    def validate_input(self) -> None:
        raise NodeValidationError("Intentional validation error for testing purposes.")

    value_in: IO.ANY = InputField(default="test")
    value_out: IO.ANY = OutputField()

    def process(self):
        logger.debug(f"ValidationErrorNode received: {self.value_in}")
        self.value_out = self.value_in
