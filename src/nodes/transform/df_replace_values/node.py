from typing import Optional

import dask.dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_mixins.column_rules import ColumnRulesMixin
from src.node_dsl.node_typing import IO
from src.nodes.transform._shared.column_rules import OPERATIONS


class DataFrameReplaceValues(ColumnRulesMixin, DFOutputBaseNode):
    COLUMN_RULE_OPERATION = OPERATIONS["replace"]
    LEGACY_RULE_INPUTS = ("column_to_replace", "dictionary",)
    LEGACY_REQUIRED = ("column_to_replace", "dictionary",)

    TITLE = "Replace values"
    ICON_KEY = "dataframe-replace-values"
    EMOJI = "🔃"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Inspect the target column's dtype and representative values. Replacements can change "
            "its effective dtype, especially when numeric or datetime conversion fails."
        ),
    )
    column_to_replace: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Select one existing column to replace in place. Use a dedicated timezone or cast node "
            "when the task is a general conversion rather than exact-value substitution."
        ),
    )
    dictionary: dict | None = InputField(
        agent_description=(
            "Map old values to replacements. The aliases null/none/nan/nil/empty string have "
            "special missing-value semantics; numeric and datetime keys are coerced to the source "
            "type. Check the README and test representative matches, nulls and output dtype before "
            "relying on mixed-type replacements."
        ),
    )

    output: dd.DataFrame = OutputField()

    def process_legacy(self):
        from src.nodes.transform._shared.legacy_replace import replace_legacy
        self.output = replace_legacy(self.df, self.column_to_replace, self.dictionary)
