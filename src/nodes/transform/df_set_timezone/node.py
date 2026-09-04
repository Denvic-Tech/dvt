import dask.dataframe as dd

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFrameSetTimezone(DFOutputBaseNode):
    TITLE = "Set Timezone"
    EMOJI = "🌐"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    column: IO.COLUMN_NAME = InputField()
    timezone: str = InputField(default="Europe/Moscow")

    output: dd.DataFrame = OutputField()

    def process(self):
        target_col = self.column
        tz = self.timezone
        logger.info(f"Setting timezone '{tz}' for column '{self.column}'")

        df = self.df
        s = df[self.column]

        if s.dtype.kind not in ("M",):
            s = dd.to_datetime(s, errors="coerce")
            logger.warning(f"Column '{self.column}' converted to datetime. Unparseable values become NaT.")

        def set_tz(series):
            if series.dt.tz is None:
                return series.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
            else:
                return series.dt.tz_convert(tz)

        result = s.map_partitions(set_tz, meta=(s.name, f"datetime64[ns, {tz}]"))

        df = df.assign(**{target_col: result})
        self.output = df
