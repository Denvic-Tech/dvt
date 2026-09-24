from typing import Optional

from dask import dataframe as dd

from src.logger import logger
from src.node_dsl import BaseNode, InputField
from src.node_dsl.runtime.integrations.file_connection.mixin import FileConnectionInputMixin
from src.nodes.write._shared.target_path import normalize_relative_target_path


class SaveCSV(FileConnectionInputMixin, BaseNode):
    TITLE = "Save CSV"
    ICON_KEY = "write-csv"
    EMOJI = "💾"
    CATEGORY = "Writing"
    OUTPUT_NODE = True

    # --- Inputs ---
    df: dd.DataFrame = InputField(
        agent_description=(
            "Connect the final DataFrame to export. Confirm selected columns, dtypes, row volume, "
            "and index policy before writing. CSV loses rich type information, and execution "
            "triggers computation of the upstream graph."
        ),
    )

    path: str = InputField(
        agent_description=(
            "Set a non-empty connection-relative target name such as reports/export.csv; the .csv "
            "suffix is normalized. Confirm that overwriting the target is intended. With "
            "single_file=false, Dask writes partition files, so inspect its resulting layout "
            "rather than assuming one file."
        ),
        description="Относительный путь к CSV-файлу, например: reports/export.csv",
    )
    delimiter: str = InputField(
        agent_description=(
            "Choose the output separator required by the consuming system. Escaped \\t is decoded "
            "and blank falls back to comma. Use a single-character CSV delimiter and keep it "
            "consistent with the reader's configuration."
        ),
        default=",",
    )
    encoding: Optional[str] = InputField(
        agent_description=(
            "Choose the output text encoding expected by consumers, normally utf-8. Use utf-8-sig "
            "when a BOM is explicitly required. A different encoding may fail for characters it "
            "cannot represent."
        ),
        default="utf-8",
    )
    index: bool = InputField(
        agent_description=(
            "Leave false unless the DataFrame index is required in the exported data. True "
            "serializes it as an additional field; inspect whether a named business key currently "
            "lives in the index before deciding."
        ),
        default=False,
    )  # Сохранять ли индекс DataFrame
    header: bool = InputField(
        agent_description=(
            "Leave true when the consumer expects column names. False writes data rows only. In "
            "single-file mode the header is emitted only for the first partition."
        ),
        default=True,
    )  # Сохранять ли заголовки
    single_file: bool = InputField(
        agent_description=(
            "Use true when the consumer requires one CSV file; writing partitions into it reduces "
            "output parallelism. Use false for partitioned output when downstream tools accept "
            "multiple files. Choose from actual volume and the required storage layout rather than "
            "keeping the default automatically."
        ),
        default=True,
    )  # Сохранить в один файл

    def _target_path(self) -> str:
        return normalize_relative_target_path(self.path, ".csv")

    def _decode_delimiter(self, value: str) -> str:
        """Преобразует escape-последовательности типа '\\t' → '\t'."""
        if not value:
            return ","
        try:
            return value.encode("utf-8").decode("unicode_escape")
        except Exception:
            # если что-то не так — просто вернуть как есть
            return value

    def process(self):
        ctx = self._get_fs_context(path=self._target_path(), create_fs=False)
        logger.info(f"Saving DataFrame to CSV: {ctx.path}, delimiter: {self.delimiter}")

        try:
            self.df.to_csv(
                ctx.path,
                sep=self._decode_delimiter(self.delimiter),
                encoding=self.encoding,
                index=self.index,
                header=self.header,
                single_file=self.single_file,
                header_first_partition_only=True if self.single_file else None,
                storage_options=ctx.storage_options
            )
            logger.info(f"DataFrame with shape {self.df.shape} saved successfully.")

        except Exception as e:
            logger.error(f"Error saving DataFrame to {self.path}: {e}")
            raise
