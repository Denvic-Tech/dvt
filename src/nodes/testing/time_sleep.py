import time

from src.logger import logger
from src.node_dsl import TestingBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class TimeSleepNode(TestingBaseNode):
    TITLE = "Time Sleep Node"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    value_in: IO.ANY = InputField(default="test")
    value_out: IO.ANY = OutputField()

    sleep_time_sec: int = InputField(default=5, min_value=1)

    def process(self):
        if not isinstance(self.sleep_time_sec, int):
            raise ValueError("Provided sleep_time_sec should be integer")

        logger.debug(f"TimeSleepNode received: {self.value_in}, sleep time: {self.sleep_time_sec}")
        time.sleep(self.sleep_time_sec)
        self.value_out = self.value_in
