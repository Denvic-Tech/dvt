from src.logger import logger
from src.node_dsl import TestingBaseNode, InputField


class SimpleOutputNode(TestingBaseNode):
    TITLE = "Simple Output"
    CATEGORY = "Testing"
    EXPERIMENTAL = True
    OUTPUT_NODE = True

    value_final: str = InputField(
        agent_description=(
            "Experimental terminal test input: the string is logged and no data output is "
            "produced. Use to verify graph execution, not to persist results."
        ),
    )

    def process(self):
        logger.debug(f"SimpleOutputNode received final value: {self.value_final}")
        # Ничего не возвращаем, т.к. это выходная нода
