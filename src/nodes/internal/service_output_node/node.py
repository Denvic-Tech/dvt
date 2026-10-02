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

    input: Optional[Any] = InputField(
        agent_description=(
            "Internal hidden sink used by service execution. Connect the value to consume; Dask "
            "DataFrames are fully computed and other values are only logged. Do not add this as a "
            "user-facing persistence destination."
        ),
        default=None,
    )

    def process(self) -> None:
        logger.info(f"Service Node: {self.input}")
        if isinstance(self.input, dd.DataFrame):
            self.input.compute()
