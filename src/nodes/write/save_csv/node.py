from typing import Optional

from dask import dataframe as dd

from src.logger import logger
from src.node_dsl import BaseNode, InputField
from src.node_dsl.runtime.integrations.file_connection.mixin import FileConnectionInputMixin
from src.nodes.write._shared.target_path import normalize_relative_target_path


class SaveCSV(FileConnectionInputMixin, BaseNode):
    TITLE = "Save CSV"
    EMOJI = "💾"
    CATEGORY = "Writing"
    OUTPUT_NODE = True

    # --- Inputs ---
    df: dd.DataFrame = InputField()

    path: str = InputField(
        description="Относительный путь к CSV-файлу, например: reports/export.csv",
    )
    delimiter: str = InputField(default=",")
    encoding: Optional[str] = InputField(default="utf-8")
    index: bool = InputField(default=False)  # Сохранять ли индекс DataFrame
    header: bool = InputField(default=True)  # Сохранять ли заголовки
    single_file: bool = InputField(default=True)  # Сохранить в один файл

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
