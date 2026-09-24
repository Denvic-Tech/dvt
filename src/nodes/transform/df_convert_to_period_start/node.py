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
    ICON_KEY = "dataframe-convert-to-period-start"
    EMOJI = "🗓️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Inspect source datetime types and timezone meaning before deriving reporting periods. "
            "This transforms a column without aggregating rows."
        ),
    )
    column: IO.COLUMN_NAME = InputField(
        agent_description=(
            "Choose the date field; non-datetime input is parsed and invalid values become NaT. "
            "Apply the intended source timezone before deriving local calendar boundaries."
        ),
    )
    period: Literal["month", "week", "year", "day", "hour", "minute", "second"] = InputField(
        agent_description=(
            "Choose the business period explicitly. Weeks start on Monday; month/year use calendar "
            "boundaries. Output is timezone-naive, so verify local-versus-UTC reporting semantics."
        ),
        default="month"
    )
    new_column: Optional[str] = InputField(
        agent_description=(
            "Omit to overwrite the original date field, or supply a distinct name to preserve it. "
            "The result is the beginning of each period, not an aggregated report."
        ),
    )

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
