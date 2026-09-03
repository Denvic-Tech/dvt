from datetime import datetime as pydatetime, UTC

import pandas as pd
import dask.dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField, IO


class GetCurrentDateTime(DFOutputBaseNode):
    TITLE = "Get Current DateTime"
    EMOJI = "🕒"
    CATEGORY = "Extraction"

    df: dd.DataFrame = InputField()
    column_name: IO.COLUMN_NAME = InputField(allow_new=True)
    output: dd.DataFrame = OutputField()

    def process(self):
        self.output = self.df.assign(**{self.column_name: pd.Timestamp.now(tz=UTC)})
