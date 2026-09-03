import dask
import pandas as pd
from dask import dataframe as dd

from core.types import Column, DataFrameMetadata, DataType

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.runtime.integrations.file_connection.mixin import FileConnectionInputMixin
from src.node_dsl.types import NodeMetadata
from src.nodes.extract.ftp_file import localized_ftp_file


def _read_ftp_csv_file(
    path: str,
    storage_options: dict,
    *,
    sep: str,
    encoding: str | None,
    usecols: list[str] | None,
    dtypes: dict[str, str] | None,
) -> pd.DataFrame:
    with localized_ftp_file(
        path,
        storage_options,
        prefix="load-csv-ftp-",
        default_suffix=".csv",
    ) as temp_path:
        return pd.read_csv(
            temp_path,
            sep=sep,
            encoding=encoding,
            usecols=usecols,
            dtype=dtypes,
        )


class LoadCSV(FileConnectionInputMixin, DFOutputBaseNode):
    TITLE = "Load CSV"
    EMOJI = "📄"
    CATEGORY = "Extraction"

    # --- Inputs ---
    path: str | None = InputField(
        default="",
        description=(
            "Поддерживаются glob-паттерны, например:\n"
            "  'reports/01-01-*.csv' — все файлы за 1 января\n"
            "  'reports/2025-*/data-*.csv' — все файлы за 2025 год"
        ),
    )
    delimiter: str = InputField(default=",")
    encoding: str | None = InputField(
        default="utf-8",
        is_hidden=True,
    )
    usecols: list[str] | None = InputField(
        default=None,
        is_hidden=True,
    )
    dtypes: dict[str, str] | None = InputField(
        default=None,
    )

    # --- Outputs ---
    output: dd.DataFrame = OutputField()

    def _decode_delimiter(self, value: str) -> str:
        """Преобразует escape-последовательности типа '\\t' → '\t'."""
        if not value:
            return ","
        try:
            return value.encode("utf-8").decode("unicode_escape")
        except Exception:
            # если что-то не так — просто вернуть как есть
            return value

    def _read_csv(self) -> dd.DataFrame:
        runtime = self._get_file_runtime(path=self.path or "")
        ctx = runtime.context
        logger.info(f"Resolved {ctx.protocol.upper()} path: {ctx.path}")

        files = runtime.list_files(
            required=True,
            subject="CSV file(s)",
            operation="listing CSV files",
        )
        if ctx.protocol == "ftp":
            delayed_parts = [
                dask.delayed(_read_ftp_csv_file)(
                    path,
                    dict(ctx.storage_options),
                    sep=self._decode_delimiter(self.delimiter),
                    encoding=self.encoding,
                    usecols=self.usecols,
                    dtypes=self.dtypes,
                )
                for path in files
            ]
            return dd.from_delayed(delayed_parts)

        kwargs = {
            "sep": self._decode_delimiter(self.delimiter),
            "encoding": self.encoding,
            "usecols": self.usecols,
            "storage_options": ctx.storage_options,
        }

        with runtime.operation("reading CSV files"):
            return dd.read_csv(ctx.path, dtype=self.dtypes, **kwargs)

    def process(self) -> None:
        logger.info(f"Loading CSV from (pattern): {self.path}")
        try:
            self.output = self._read_csv()
            logger.info(f"Loaded DataFrame with shape: {self.output.shape}")

        except FileNotFoundError as exc:
            logger.error(f"CSV file(s) not found at {self.path}: {exc}")
            raise

        except Exception as e:
            logger.error(f"Error loading CSV from {self.path}: {e}")
            raise

    def infer_metadata(self) -> NodeMetadata:
        try:
            logger.info(f"Infer metadata for CSV: {self.path}")

            ddf = self._read_csv()

            columns: list[Column] = []
            for col, dtype in ddf.dtypes.items():
                columns.append(
                    Column(
                        name=col,
                        dtype=DataType.from_type(dtype),
                        nullable=True,
                        index=(col == ddf.index.name),
                    )
                )

            meta = {
                "output": DataFrameMetadata(columns=columns)
            }
            return meta

        except Exception as e:
            logger.error(f"Error inferring metadata for CSV {self.path}: {e}")
            raise
