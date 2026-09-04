from dask import dataframe as dd

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.utils.testing import types_testing_dataframe


class DTypesDataFrameOutputNode(DFOutputBaseNode):
    TITLE = "DataFrame with All dtypes"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    num_rows: int = InputField(default=1000)
    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info("Generating DataFrame with various data types.")
        df = types_testing_dataframe(self.num_rows)
        self.output = dd.from_pandas(df, npartitions=1)
