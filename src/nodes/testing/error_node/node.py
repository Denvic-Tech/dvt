from src.logger import logger
from src.node_dsl import TestingBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class ErrorNode(TestingBaseNode):
    TITLE = "Error Node"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    value_in: IO.ANY = InputField(
        agent_description=(
            "Experimental failure fixture. Any supplied value is logged, then execution raises the "
            "intentional Error in ErrorNode exception. Use only when testing failure handling; it "
            "never produces a successful value_out."
        ),
        default="test",
    )
    value_out: IO.ANY = OutputField()

    def process(self):
        logger.debug(f"ErrorNode received: {self.value_in}")
        raise Exception("Error in ErrorNode")
