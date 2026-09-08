from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.logger import logger


class DataFrameQuery(DFOutputBaseNode):
    TITLE = "Query DataFrame"
    CATEGORY = "Transform"
    EXPERIMENTAL = True

    df: dd.DataFrame = InputField()
    query: str = InputField(multiline=True)  # pandas query string

    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info(f"Applying query: {self.query}")
        try:
            self.output = self.df.query(self.query, engine='python')  # Используем 'python' engine для большей гибкости
            logger.info(f"Query DataFrame result shape: {self.output.shape}")
        except Exception as e:
            logger.error(f"Error executing DataFrame query '{self.query}': {e}")
            raise
