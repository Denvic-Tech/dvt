from typing import Optional

from dask import dataframe as dd
from pydantic import Field

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, NodeValidationError, OutputField
from src.node_dsl.node_mixins.column_rules import (
    ColumnRulesMixin,
    RuleModel,
    resolve_input_bindings,
)
from src.node_dsl.node_typing import IO
from src.nodes.transform._shared.column_rules import OPERATIONS


class CalculatedColumn(RuleModel):
    name: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    overwrite_existing: bool = False
    input_bindings: dict[str, str] = Field(default_factory=dict)


class DataFrameAddColumnByExpression(ColumnRulesMixin, DFOutputBaseNode):
    COLUMN_RULE_OPERATION = OPERATIONS["expression"]
    LEGACY_RULE_INPUTS = ("column_name", "expression",)
    LEGACY_REQUIRED = (
        "column_name",
        "expression",
    )

    TITLE = "Add/Modify Column By Expression"
    CATEGORY = "Transform"
    EXPERIMENTAL = True

    df: dd.DataFrame = InputField(
        agent_description=(
            "Experimental expression node: inspect existing fields and types and prefer a stable "
            "specialized transform when available."
        ),
    )
    column_name: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Choose the field to assign; an existing field is overwritten. Check downstream "
            "references and preserve the source under a different name when needed."
        ),
        allow_new=True,
    )
    expression: str | None = InputField(
        agent_description=(
            "Use a pandas/Dask eval value expression for the target field, not SQL or a DVT "
            "template. Test supported operators and dtypes; the Python engine does not make "
            "arbitrary statements valid."
        ),
        multiline=True,
    )

    calculated_columns: list[CalculatedColumn] | None = InputField(
        default=None,
        description="Named expressions evaluated independently against the original input.",
    )
    output: dd.DataFrame = OutputField()

    async def _base_validate(self):
        if self.calculated_columns is None:
            await super()._base_validate()
        else:
            await DFOutputBaseNode._base_validate(self)
            if self.column_rules is not None:
                raise NodeValidationError("Choose calculated_columns or column_rules, not both.")
            self._calculated_results()

    def _calculated_results(self):
        if not self.calculated_columns:
            raise NodeValidationError("Add at least one calculated column.")
        results = {}
        for raw in self.calculated_columns:
            entry = CalculatedColumn.model_validate(resolve_input_bindings(self, raw))
            if entry.name in results or (
                entry.name in self.df.columns and not entry.overwrite_existing
            ):
                raise NodeValidationError(f"Result column '{entry.name}' already exists.")
            result = self.df.eval(entry.expression, engine="python")
            if isinstance(result, dd.DataFrame):
                if entry.overwrite_existing and len(result.columns) == 1:
                    result = result[result.columns[0]]
                else:
                    raise NodeValidationError("Use a value expression, not an assignment.")
            results[entry.name] = result
        return results

    def process(self):
        if self.calculated_columns is not None:
            self.output = self.df.assign(**self._calculated_results())
        else:
            super().process()

    def process_legacy(self):
        logger.info(
            f"Evaluating expression for column column_name{self.column_name}, expression={self.expression}"
        )
        try:
            self.df[self.column_name] = self.df.eval(self.expression, engine="python")
            self.output = self.df
            logger.info(
                f"Expression evaluated successfully. Resulting dtypes: {self.output.dtypes}"
            )

        except Exception as e:
            logger.error(f"Error evaluating expression '{self.expression}': {e}")
            raise
