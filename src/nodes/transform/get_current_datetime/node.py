from datetime import datetime as pydatetime, UTC

import pandas as pd
import dask.dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField, IO


class GetCurrentDateTime(DFOutputBaseNode):
    TITLE = "Get Current DateTime"
    ICON_KEY = "current-datetime"
    EMOJI = "🕒"
    CATEGORY = "Extraction"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Connect rows to annotate with one timestamp captured when the node processes the "
            "DataFrame. The value changes across fresh executions; it is not an event timestamp "
            "from the source."
        ),
    )
    column_name: IO.COLUMN_NAME = InputField(
        agent_description=(
            "Choose the field to receive the current UTC-aware timestamp. Existing data under that "
            "name is overwritten; use a dedicated load-time field when source timestamps must "
            "survive."
        ),
        allow_new=True,
    )
    output: dd.DataFrame = OutputField()

    def process(self):
        self.output = self.df.assign(**{self.column_name: pd.Timestamp.now(tz=UTC)})
