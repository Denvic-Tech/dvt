from typing import Optional, Any

import dask.dataframe as dd

from src.logger import logger
from src.node_dsl import InternalBaseNode, InputField


class ServiceOutputNode(InternalBaseNode):
    TITLE = "Service Node"
    EMOJI = "📤"
    CATEGORY = "Internal"
    OUTPUT_NODE = True
    VISIBLE = False

    input: Optional[Any] = InputField(default=None)

    def process(self) -> None:
        logger.info(f"Service Node: {self.input}")
        if isinstance(self.input, dd.DataFrame):
            self.input.compute()
