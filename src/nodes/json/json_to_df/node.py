from typing import Literal

import pandas as pd
from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField, IO
from src.logger import logger


class JsonToDataFrame(DFOutputBaseNode):
    TITLE = "JSON → DataFrame"
    ICON_KEY = "json-to-dataframe"
    EMOJI = "{ }"
    CATEGORY = "JSON"

    json: IO.JSON = InputField(
        agent_description=(
            "Provide a parsed JSON object or list of row objects, not serialized JSON text. A "
            "single object becomes one row; nested objects/lists remain cell values, so "
            "flatten/explode beforehand when tabular columns are required. Construction "
            "materializes the input in pandas before creating Dask partitions."
        ),
    )
    orient: Literal["columns", "index", "tight"] = InputField(
        agent_description=(
            "This compatibility setting is currently not used by conversion: all choices call the "
            "same pandas DataFrame constructor, wrapping a dictionary as one record. Do not expect "
            "columns/index/tight decoding or a round trip for those encodings; normalize the JSON "
            "into row objects first."
        ),
        default="columns",
    )

    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info(f"Converting JSON string (orient='{self.orient}') to DataFrame")

        if isinstance(self.json, dict):
            self.json = [self.json]

        # Используем StringIO, чтобы pandas корректно работал со строкой как с файлом
        npartitions = max(1, len(self.json) // 100000)

        pdf = pd.DataFrame(self.json)
        df = dd.from_pandas(pdf, npartitions=npartitions)

        self.output = df
        logger.info(f"Converted DataFrame shape: {self.output.shape}")