from src.logger import logger
from src.node_dsl import TestingBaseNode, InputField, OutputField


class SimpleInputNode(TestingBaseNode):
    TITLE = "Simple Input"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    value_in: str = InputField(
        agent_description=(
            "Experimental test input. The node emits a string formed by prefixing this value with "
            "'Processed: '. Use only for simple pipeline wiring tests, not as a production data "
            "source."
        ),
        default="test",
    )
    value_out: str = OutputField()

    def process(self):
        logger.debug(f"SimpleInputNode received: {self.value_in}")
        self.value_out = f"Processed: {self.value_in}"
