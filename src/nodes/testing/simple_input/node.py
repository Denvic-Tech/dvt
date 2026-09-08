from src.logger import logger
from src.node_dsl import TestingBaseNode, InputField, OutputField


class SimpleInputNode(TestingBaseNode):
    TITLE = "Simple Input"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    value_in: str = InputField(default="test")
    value_out: str = OutputField()

    def process(self):
        logger.debug(f"SimpleInputNode received: {self.value_in}")
        self.value_out = f"Processed: {self.value_in}"
