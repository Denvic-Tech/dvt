import pandas as pd
from dask import dataframe as dd

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField


class DataFrameTestOutputNode(DFOutputBaseNode):
    TITLE = "Test Output DataFrame"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    rows: int = InputField(
        agent_description=(
            "Experimental test fixture setting. The current generator repeatedly overwrites the "
            "same column keys, so for positive rows/columns the output height is determined by "
            "columns, not this requested row count. Use only for tests and verify actual shape; do "
            "not use it for representative volume benchmarks."
        ),
        default=3,
    )
    columns: int = InputField(
        agent_description=(
            "Experimental fixture: choose a small positive integer. It determines both the number "
            "of generated columns and the length of each column in the current implementation. The "
            "result is a single in-memory partition."
        ),
        default=2,
    )
    prefix: str = InputField(
        agent_description=(
            "Set the prefix for generated test column names, followed by one-based numbers such as "
            "col_1. Keep names compatible with downstream test expectations; this affects names "
            "only."
        ),
        default="col_",
    )

    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info(f"Generating test DataFrame with {self.rows} rows and {self.columns} columns.")
        data = {
            f"{self.prefix}{j + 1}": range(i * self.columns + 1, (i + 1) * self.columns + 1)
            for i in range(self.rows) for j in range(self.columns)
        }
        df = pd.DataFrame(data)
        self.output = dd.from_pandas(df, npartitions=1)
