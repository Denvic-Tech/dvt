from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.logger import logger


class DataFrameQuery(DFOutputBaseNode):
    TITLE = "Query DataFrame"
    CATEGORY = "Transform"
    EXPERIMENTAL = True

    df: dd.DataFrame = InputField(
        agent_description=(
            "Experimental query node: prefer the structured filter node when it expresses the "
            "condition. Inspect field types and nulls before evaluating a query."
        ),
    )
    query: str = InputField(
        agent_description=(
            "Use a pandas/Dask query expression, not SQL. Quote unusual field names appropriately "
            "and test null behavior. This executes through the Python query engine; it is distinct "
            "from DVT input-template expressions."
        ),
        multiline=True,
    )  # pandas query string

    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info(f"Applying query: {self.query}")
        try:
            self.output = self.df.query(self.query, engine='python')  # Используем 'python' engine для большей гибкости
            logger.info(f"Query DataFrame result shape: {self.output.shape}")
        except Exception as e:
            logger.error(f"Error executing DataFrame query '{self.query}': {e}")
            raise
