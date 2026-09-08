from typing import Literal

import pandas as pd
from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField, IO
from src.logger import logger


class JsonToDataFrame(DFOutputBaseNode):
    TITLE = "JSON → DataFrame"
    EMOJI = "{ }"
    CATEGORY = "JSON"

    json: IO.JSON = InputField()
    orient: Literal["columns", "index", "tight"] = InputField(default="columns")

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