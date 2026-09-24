import time

from src.logger import logger
from src.node_dsl import TestingBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class TimeSleepNode(TestingBaseNode):
    TITLE = "Time Sleep Node"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    value_in: IO.ANY = InputField(
        agent_description=(
            "Experimental test value forwarded unchanged to value_out after the configured delay. "
            "Use to test timing and orchestration behavior."
        ),
        default="test",
    )
    value_out: IO.ANY = OutputField()

    sleep_time_sec: int = InputField(
        agent_description=(
            "Set a positive integer delay in seconds. This calls blocking sleep and occupies the "
            "worker execution slot; use small values for intentional timing tests, not for "
            "production scheduling or retry policy."
        ),
        default=5, min_value=1,
    )

    def process(self):
        if not isinstance(self.sleep_time_sec, int):
            raise ValueError("Provided sleep_time_sec should be integer")

        logger.debug(f"TimeSleepNode received: {self.value_in}, sleep time: {self.sleep_time_sec}")
        time.sleep(self.sleep_time_sec)
        self.value_out = self.value_in
