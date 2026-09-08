from src.logger import logger
from src.node_dsl import TestingBaseNode


class LogVariablesNode(TestingBaseNode):
    TITLE = "Log Variables"
    CATEGORY = "Testing"
    EXPERIMENTAL = True
    OUTPUT_NODE = True

    def process(self):
        logger.debug(f"LogVariablesNode received. Variables:")
        for var_name, var in self.input_variables.items():
            logger.debug(f"\t{var_name}: {var}")
