import dask.dataframe as dd

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFrameSetTimezone(DFOutputBaseNode):
    TITLE = "Set Timezone"
    ICON_KEY = "dataframe-set-timezone"
    EMOJI = "🌐"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Connect data with known source timezone semantics. Do not assume a naive timestamp is "
            "already local time; inspect representative values before conversion."
        ),
    )
    column: IO.COLUMN_NAME = InputField(
        agent_description=(
            "Select the datetime field to update. Non-datetime values are parsed with errors "
            "coerced to NaT; inspect parsing loss and daylight-saving boundary cases."
        ),
    )
    timezone: str = InputField(
        agent_description=(
            "Use an explicit timezone supported by the runtime. Naive values are localized without "
            "shifting clock time; aware values are converted preserving instants. "
            "Ambiguous/nonexistent local times become NaT. For naive UTC input, localize to UTC "
            "before converting to a local zone."
        ),
        default="Europe/Moscow",
    )

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
