import json
from typing import Literal

from dask import dataframe as dd

from core.metadata.json_utils import json_safe
from src.logger import logger
from src.node_dsl import IO, InputField, JSONOutputBaseNode, OutputField


class DataFrameToJson(JSONOutputBaseNode):
    TITLE = "DataFrame → JSON"
    EMOJI = "{ }"
    CATEGORY = "JSON"

    df: dd.DataFrame = InputField()
    orient: Literal["columns", "index", "tight"] = InputField(default="columns")

    output: IO.JSON = OutputField()

    def process(self):
        logger.info(f"Converting DataFrame to JSON (orient='{self.orient}')")

        # Convert to pandas first because dask.to_json writes to storage and returns paths.
        pdf = self.df.compute()

        # Use pandas JSON encoder to make the result JSON-serializable (datetimes, NaN, etc.).
        # Note: Some pandas versions don't support orient='tight' in to_json, so handle it separately.
        if self.orient in ("columns", "index"):
            payload = pdf.to_json(orient=self.orient, date_format="iso", default_handler=str)
            self.output = json.loads(payload)
            return

        data = pdf.to_dict(orient="tight")
        self.output = json_safe(data)
