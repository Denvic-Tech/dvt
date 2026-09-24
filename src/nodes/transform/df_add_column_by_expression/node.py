from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO
from src.logger import logger


class DataFrameAddColumnByExpression(DFOutputBaseNode):
    TITLE = "Add/Modify Column By Expression"
    CATEGORY = "Transform"
    EXPERIMENTAL = True

    df: dd.DataFrame = InputField(
        agent_description=(
            "Experimental expression node: inspect existing fields and types and prefer a stable "
            "specialized transform when available."
        ),
    )
    column_name: IO.COLUMN_NAME = InputField(
        agent_description=(
            "Choose the field to assign; an existing field is overwritten. Check downstream "
            "references and preserve the source under a different name when needed."
        ),
        allow_new=True,
    )
    expression: str = InputField(
        agent_description=(
            "Use a pandas/Dask eval value expression for the target field, not SQL or a DVT "
            "template. Test supported operators and dtypes; the Python engine does not make "
            "arbitrary statements valid."
        ),
        multiline=True,
    )

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
