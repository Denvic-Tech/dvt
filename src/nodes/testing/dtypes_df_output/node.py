from dask import dataframe as dd

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.utils.testing import types_testing_dataframe


class DTypesDataFrameOutputNode(DFOutputBaseNode):
    TITLE = "DataFrame with All dtypes"
    CATEGORY = "Testing"
    EXPERIMENTAL = True

    num_rows: int = InputField(
        agent_description=(
            "Experimental synthetic dtype fixture. Choose a small non-negative row count suitable "
            "for testing; all data is generated in memory and put in one Dask partition. Inspect "
            "the emitted schema rather than treating this as a real source or production-scale "
            "benchmark."
        ),
        default=1000,
    )
    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info("Generating DataFrame with various data types.")
        df = types_testing_dataframe(self.num_rows)
        self.output = dd.from_pandas(df, npartitions=1)
