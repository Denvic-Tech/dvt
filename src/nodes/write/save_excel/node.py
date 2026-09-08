import posixpath as ppath

import dask
import dask.dataframe as dd
import pandas as pd
from loguru import logger

from src.node_dsl import BaseNode, InputField
from src.node_dsl.runtime.integrations.file_connection.mixin import FileConnectionInputMixin
from src.nodes.write._shared.target_path import normalize_relative_target_path


class SaveExcel(FileConnectionInputMixin, BaseNode):
    TITLE = "Save Excel"
    EMOJI = "💾"
    CATEGORY = "Writing"
    OUTPUT_NODE = True

    # --- Inputs ---
    df: dd.DataFrame = InputField()

    path: str = InputField(
        description="Относительный путь к XLSX-файлу, например: reports/export.xlsx",
    )

    sheet_name: str = InputField(default="Sheet1")
    index: bool = InputField(default=False)
    header: bool = InputField(default=True)
    single_file: bool = InputField(default=True)

    _MAX_ROWS = 1_048_576
    _MAX_COLS = 16_384

    def _target_path(self) -> str:
        return normalize_relative_target_path(self.path, ".xlsx")

    def _target_key_single(self) -> str:
        return self._target_path()

    def _base_key_for_parts(self) -> str:
        return self._target_key_single()

    def _part_key(self, base_key: str, i: int) -> str:
        """
        <dir>/<file>.xlsx -> <dir>/<file>-part-00000.xlsx
        <dir>/<file>      -> <dir>/<file>-part-00000.xlsx
        <dir>/                -> <dir>/part-00000.xlsx
        """
        base_dir, base_name = ppath.split(base_key)
        if base_name.lower().endswith(".xlsx"):
            stem = base_name[:-5]
            fname = f"{stem}-part-{i:05d}.xlsx"

        elif base_name:
            fname = f"{base_name}-part-{i:05d}.xlsx"

        else:
            fname = f"part-{i:05d}.xlsx"

        return ppath.join(base_dir, fname)

    def process(self):
        ctx = self._get_fs_context(root_only=True)

        logger.info(
            f"Saving DataFrame to Excel: path={ctx.path}, "
            f"single_file={self.single_file}"
        )

        try:
            if self.single_file:
                pdf: pd.DataFrame = self.df.compute()
                n_rows, n_cols = pdf.shape
                if n_rows > self._MAX_ROWS or n_cols > self._MAX_COLS:
                    raise ValueError(
                        f"Excel sheet limit exceeded: got {n_rows}x{n_cols}, "
                        f"but max is {self._MAX_ROWS}x{self._MAX_COLS}. "
                        f"Set single_file=False to write partitioned .xlsx files."
                    )

                key = self._target_key_single()
                url = f"{ctx.path.rstrip('/')}/{key}"

                # Используем ctx.fs.open вместо передачи URL строки в pandas
                # Это гарантирует использование fsspec (как в SaveCSV/SaveParquet)
                with ctx.fs.open(url, "wb") as f:
                    logger.debug(f"Writing single Excel file to: '{url}'")
                    with pd.ExcelWriter(f, engine="openpyxl") as writer:
                        pdf.to_excel(
                            writer,
                            sheet_name=self.sheet_name,
                            index=self.index,
                            header=self.header,
                        )
                logger.info(f"Saved single Excel file to {url} | shape={pdf.shape}")

            else:
                parts = self.df.to_delayed()
                if parts and isinstance(parts[0], (list, tuple)):
                    flat_parts = []
                    for p in parts:
                        flat_parts.extend(p if isinstance(p, (list, tuple)) else [p])
                    parts = flat_parts

                base_key = self._base_key_for_parts()

                @dask.delayed
                def _write_one(pdf_part: pd.DataFrame, rel_key: str) -> str:
                    url = f"{ctx.path.rstrip('/')}/{rel_key}"
                    logger.debug(f"Writing Excel file part to: '{url}'")
                    # Используем ctx.fs.open внутри delayed задачи
                    with ctx.fs.open(url, "wb") as f:
                        with pd.ExcelWriter(f, engine="openpyxl") as writer:
                            pdf_part.to_excel(
                                writer,
                                sheet_name=self.sheet_name,
                                index=self.index,
                                header=self.header,
                            )
                    return url

                tasks = []
                for i, part in enumerate(parts):
                    part_key = self._part_key(base_key, i)
                    tasks.append(_write_one(part, part_key))

                written_urls = dask.compute(*tasks)
                example = written_urls[0] if written_urls else "—"
                logger.info(f"Saved {len(written_urls)} Excel part files to {ctx.protocol.upper()}. Example: {example}")

        except Exception as e:
            logger.error(
                f"Error saving Excel (path={ctx.path}): {e}"
            )
            raise
