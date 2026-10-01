import dask.dataframe as dd
import pandas as pd
import pytest

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_mixins.column_rules import (
    ColumnRuleOperation,
    ColumnRulesMixin,
    RuleModel,
)
from src.pipeline.execution_mode import PipelineExecutionMode


class ScaleParams(RuleModel):
    factor: int = 2


def scale_column(df, item):
    return {item.targets[0]: df[item.source] * item.params.factor}


class ScaleColumns(ColumnRulesMixin, DFOutputBaseNode):
    """An extension can supply semantics without a built-in transform dependency."""

    COLUMN_RULE_OPERATION = ColumnRuleOperation(
        params_model=ScaleParams, transform=scale_column, compatible_kinds=("number",)
    )
    LEGACY_REQUIRED = ("column",)
    df: dd.DataFrame = InputField()
    column: str | None = InputField(default=None)
    output: dd.DataFrame = OutputField()

    def process_legacy(self):
        self.output = self.df.assign(**{self.column: self.df[self.column] * 2})


@pytest.mark.asyncio
async def test_extension_operation_uses_mixin_for_validation_and_execution():
    df = dd.from_pandas(pd.DataFrame({"amount": [3], "count": [4]}), 1)
    node = ScaleColumns(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        df=df,
        column_rules=[
            {
                "id": "scale",
                "selector": {"tokens": [{"kind": "all"}]},
                "params": {"factor": 3},
                "output": {"mode": "new", "suffix": "_scaled"},
            }
        ],
    )
    await node.execute(PipelineExecutionMode.FULL)
    assert node.output.compute().iloc[0].to_dict() == {
        "amount": 3,
        "count": 4,
        "amount_scaled": 9,
        "count_scaled": 12,
    }


@pytest.mark.asyncio
async def test_mixin_legacy_path_and_incompatible_types():
    from src.node_dsl import NodeValidationError

    df = dd.from_pandas(pd.DataFrame({"amount": [3], "label": ["x"]}), 1)
    legacy = ScaleColumns(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        df=df,
        column="amount",
    )
    await legacy.execute(PipelineExecutionMode.FULL)
    assert legacy.output.compute()["amount"].tolist() == [6]

    node = ScaleColumns(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        df=df,
        column_rules=[{"id": "scale", "selector": {"tokens": [{"kind": "all"}]}}],
    )
    with pytest.raises(NodeValidationError, match="label.*number"):
        await node.validate()
