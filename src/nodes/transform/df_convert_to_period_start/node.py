from typing import Literal, Optional
import dask.dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO
from src.logger import logger

_FREQ = {
    "month": "MS",
    "week": "W-MON",
    "year": "AS",
    "day": "D",
    "hour": "H",
    "minute": "T",
    "second": "S",
}


class DataFrameConvertToPeriodStart(DFOutputBaseNode):
    TITLE = "Datetime → Period Start"
    EMOJI = "🗓️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    column: IO.COLUMN_NAME = InputField()
    period: Literal["month", "week", "year", "day", "hour", "minute", "second"] = InputField(
        default="month"
    )
    new_column: Optional[str] = InputField()

    output: dd.DataFrame = OutputField()

    def process(self):
        target_col = self.new_column or self.column
        logger.info(f"Converting '{self.column}' to start of '{self.period}', result -> '{target_col}'")

        df = self.df
        s = df[self.column]

        if s.dtype.kind not in ("M"):
            s = dd.to_datetime(s, errors="coerce")
            logger.warning(f"Непарсимые значения в '{self.column}' станут NaT (errors='coerce').")

        freq = _FREQ[self.period]

        try:
            result = s.dt.floor(freq)
        except ValueError:
            if self.period == "week":
                result = (s - dd.to_timedelta(s.dt.weekday, unit="D")).dt.floor("D")
            elif self.period == "month":
                def month_start(x):
                    x = x.dt.normalize()
                    return x.map(lambda ts: ts.replace(day=1) if not pd.isna(ts) else ts)
                import pandas as pd
                result = s.map_partitions(month_start, meta=("date", "datetime64[ns]"))
            elif self.period == "year":
                def year_start(x):
                    x = x.dt.normalize()
                    return x.map(lambda ts: ts.replace(month=1, day=1) if not pd.isna(ts) else ts)
                import pandas as pd
                result = s.map_partitions(year_start, meta=("date", "datetime64[ns]"))
            else:
                raise

        def to_without_tz(x):
            return x.dt.tz_localize(None)

        result = result.map_partitions(to_without_tz, meta=("date", "datetime64[ns]"))

        df = df.assign(**{target_col: result})
        self.output = df
