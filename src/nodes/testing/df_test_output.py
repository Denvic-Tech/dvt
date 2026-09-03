import pandas as pd
from dask import dataframe as dd

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField


class DataFrameTestOutputNode(DFOutputBaseNode):
    TITLE = "Test Output DataFrame"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    rows: int = InputField(default=3)
    columns: int = InputField(default=2)
    prefix: str = InputField(default="col_")

    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info(f"Generating test DataFrame with {self.rows} rows and {self.columns} columns.")
        data = {
            f"{self.prefix}{j + 1}": range(i * self.columns + 1, (i + 1) * self.columns + 1)
            for i in range(self.rows) for j in range(self.columns)
        }
        df = pd.DataFrame(data)
        self.output = dd.from_pandas(df, npartitions=1)
