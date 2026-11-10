from typing import Dict, Optional

from dask import dataframe as dd

from core.utils import is_internal_dvt_name
from core.utils.dataframe_index import carry_physical_index

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField


class DataFrameRenameColumns(DFOutputBaseNode):
    TITLE = "Rename Columns"
    ICON_KEY = "rename-columns"
    EMOJI = "✏️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Inspect columns and the named index before renaming; update downstream references to "
            "the new names."
        ),
    )
    # Словарь переименования: {"old_name": "new_name", ...}
    mapping: Optional[Dict[str, str]] = InputField(
        agent_description=(
            "Use {old_name: new_name}; omission passes the input through. A matching named index "
            "is renamed too. Ensure final names are unique and verify all intended source names "
            "exist rather than relying on silent handling of unknown keys."
        ),
        default=None,
    )

    output: dd.DataFrame = OutputField()

    def process(self):
        if self.mapping is None:
            logger.warning("No mapping provided for renaming columns. Skipping renaming.")
            self.output = self.df
            return

        result = self.df

        index_name = result.index.name
        if (
            index_name is not None
            and not is_internal_dvt_name(index_name)
            and index_name in self.mapping
        ):
            new_index_name = self.mapping[index_name]
            result = result.rename_axis(new_index_name)

        logger.info(f"Renaming columns: {self.mapping}")
        result = result.rename(columns=self.mapping)

        self.output = carry_physical_index(self.df, result, rename=self.mapping)
