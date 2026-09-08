from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO
from src.logger import logger


class DataFrameAddColumnByExpression(DFOutputBaseNode):
    TITLE = "Add/Modify Column By Expression"
    CATEGORY = "Transform"
    EXPERIMENTAL = True

    df: dd.DataFrame = InputField()
    column_name: IO.COLUMN_NAME = InputField(allow_new=True)
    expression: str = InputField(multiline=True)

    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info(f"Evaluating expression for column column_name{self.column_name}, expression={self.expression}")
        try:
            self.df[self.column_name] = self.df.eval(self.expression, engine='python')
            self.output = self.df
            logger.info(f"Expression evaluated successfully. Resulting dtypes: {self.output.dtypes}")

        except Exception as e:
            logger.error(f"Error evaluating expression '{self.expression}': {e}")
            raise
