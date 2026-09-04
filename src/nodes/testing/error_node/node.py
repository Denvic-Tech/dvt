from src.logger import logger
from src.node_dsl import TestingBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class ErrorNode(TestingBaseNode):
    TITLE = "Error Node"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    value_in: IO.ANY = InputField(default="test")
    value_out: IO.ANY = OutputField()

    def process(self):
        logger.debug(f"ErrorNode received: {self.value_in}")
        raise Exception("Error in ErrorNode")
