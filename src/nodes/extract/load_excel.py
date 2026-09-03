import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

import dask
import dask.dataframe as dd
import pandas as pd
from loguru import logger
from pandas.api.types import is_bool_dtype, is_numeric_dtype, pandas_dtype

from core.types import Column, DataFrameMetadata, DataType, FsCtx

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.runtime.integrations.file_connection.mixin import FileConnectionInputMixin
from src.node_dsl.types import NodeMetadata
from src.nodes.extract.ftp_file import localized_ftp_file


class LoadExcel(FileConnectionInputMixin, DFOutputBaseNode):
    TITLE = "Load Excel"
    EMOJI = "📊"
    CATEGORY = "Extraction"

    # --- Inputs ---
    path: str = InputField(
        description=(
            "Поддерживаются glob-паттерны, например:\n"
            "  'reports/01-01-*.excel' — все файлы за 1 января\n"
            "  'reports/2025-*/data-*.excel' — все файлы за 2025 год"
        )
    )

    sheet_name: str | None = InputField(
        default="0",
    )

    usecols: list[str] | None = InputField(
        default=None,
        is_hidden=True,
    )

    usecols_range: str | None = InputField(
        default=None,
        is_hidden=True,
    )

    dtypes: dict[str, str] | None = InputField(
        default=None,
        description=(
            "Явные типы столбцов в формате {имя_столбца: dtype}, например {'amount': 'Float64'}"
        ),
    )

    thousands: str | None = InputField(
        default=None,
        description=("Разделитель тысяч для чисел, сохраненных в Excel как текст, например пробел"),
    )

    decimal: str = InputField(
        default=".",
        description=("Десятичный разделитель для чисел, сохраненных в Excel как текст"),
    )

    header_row: int = InputField(
        default=0,
        is_hidden=True,
    )

    read_timeout_sec: int | None = InputField(
        default=None,
        min_value=1,
        description="Таймаут чтения одного Excel-файла в секундах",
    )

    # --- Outputs ---
    output: dd.DataFrame = OutputField()

    _SAMPLE_ROWS: int = 32
    _EXCEL_ERROR_VALUES: tuple[str, ...] = (
        "#NULL!",
        "#DIV/0!",
        "#VALUE!",
        "#REF!",
        "#NAME?",
        "#NUM!",
        "#N/A",
        "#GETTING_DATA",
        "#SPILL!",
        "#CALC!",
        "#FIELD!",
        "#DATA!",
        "#UNKNOWN!",
        "#BLOCKED!",
        "#CONNECT!",
        "#BUSY!",
        "#ПУСТО!",
        "#ДЕЛ/0!",
        "#ЗНАЧ!",
        "#ССЫЛКА!",
        "#ИМЯ?",
        "#ЧИСЛО!",
        "#Н/Д",
        "#ПОЛУЧЕНИЕ_ДАННЫХ",
        "#ПЕРЕНОС!",
        "#ВЫЧИСЛ!",
        "#ПОЛЕ!",
        "#ДАННЫЕ!",
        "#НЕИЗВЕСТНО!",
        "#ЗАБЛОКИРОВАНО!",
        "#ПОДКЛЮЧЕНИЕ!",
        "#ЗАНЯТО!",
    )

    def _parse_sheet(self) -> Any:
        if self.sheet_name is None or str(self.sheet_name).strip() == "":
            return 0

        sheet_name = str(self.sheet_name).strip()
        return int(sheet_name) if sheet_name.isdigit() else sheet_name

    def _resolve_usecols(self) -> list[str] | str | None:
        if self.usecols:
            return list(self.usecols)
        if self.usecols_range:
            return self.usecols_range
        return None

    def _read_excel_kwargs(self, *, nrows: int | None = None) -> dict[str, Any]:
        self._validate_numeric_separators()
        kwargs: dict[str, Any] = {
            "sheet_name": self._parse_sheet(),
            "usecols": self._resolve_usecols(),
            "index_col": None,
            "header": self.header_row,
            "engine": "openpyxl",
            "engine_kwargs": {"read_only": True, "data_only": True},
            "dtype_backend": "numpy_nullable",
            "decimal": self.decimal,
            "na_values": self._EXCEL_ERROR_VALUES,
        }
        if self.thousands is not None:
            kwargs["thousands"] = self.thousands
        if self.dtypes:
            for column_name, dtype_name in self.dtypes.items():
                try:
                    pandas_dtype(dtype_name)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Unsupported dtype '{dtype_name}' for Excel column '{column_name}'"
                    ) from exc
            kwargs["dtype"] = dict(self.dtypes)
        if nrows is not None:
            kwargs["nrows"] = nrows
        return kwargs

    def _validate_numeric_separators(self) -> None:
        if not isinstance(self.decimal, str) or len(self.decimal) != 1:
            raise ValueError("Excel decimal separator must be exactly one character")

        if self.thousands is not None:
            if not isinstance(self.thousands, str) or len(self.thousands) != 1:
                raise ValueError("Excel thousands separator must be exactly one character")
            if self.thousands == self.decimal:
                raise ValueError("Excel thousands and decimal separators must be different")

    def _normalize_dataframe_dtypes(self, df: pd.DataFrame) -> pd.DataFrame:
        explicit_columns = set(self.dtypes or {})
        unknown_columns = explicit_columns.difference(df.columns)
        if unknown_columns:
            rendered_columns = ", ".join(sorted(map(str, unknown_columns)))
            raise ValueError(
                "Explicit Excel dtypes reference columns that are absent from the selected "
                f"sheet: {rendered_columns}"
            )

        float_columns = {
            column_name: "Float64"
            for column_name, dtype in df.dtypes.items()
            if column_name not in explicit_columns
            and is_numeric_dtype(dtype)
            and not is_bool_dtype(dtype)
        }
        if float_columns:
            return df.astype(float_columns)
        return df

    def _run_with_timeout(
        self,
        fn,
        *,
        mode: str,
        path: str,
    ) -> pd.DataFrame:
        timeout_sec = self.read_timeout_sec
        if timeout_sec is None:
            return fn()

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="load-excel")
        future = executor.submit(fn)
        try:
            result = future.result(timeout=timeout_sec)
        except FuturesTimeoutError as exc:
            logger.error(
                f"[{mode}] ТАЙМАУТ {timeout_sec}s при чтении Excel "
                f"(рабочий поток продолжает висеть в фоне): path={path}"
            )
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise TimeoutError(
                f"Timed out reading Excel in {mode} mode: path={path}, timeout={timeout_sec}s"
            ) from exc
        except Exception:
            executor.shutdown(wait=True, cancel_futures=False)
            raise
        else:
            executor.shutdown(wait=True, cancel_futures=False)
            return result

    def _read_excel_via_fs(
        self,
        ctx: FsCtx,
        path: str,
        *,
        mode: str,
        nrows: int | None = None,
    ) -> pd.DataFrame:
        kwargs = self._read_excel_kwargs(nrows=nrows)

        def _read_sync() -> pd.DataFrame:
            read_start = time.perf_counter()
            logger.info(
                f"[{mode}] Старт чтения Excel: protocol={ctx.protocol}, "
                f"path={path}, nrows={nrows}, timeout={self.read_timeout_sec}"
            )
            try:
                if ctx.protocol == "ftp":
                    # --- ОБРАБОТКА (скачивание файла с FTP во временный файл) ---
                    io_start = time.perf_counter()
                    with localized_ftp_file(
                        path,
                        ctx.storage_options,
                        prefix="load-excel-ftp-",
                        default_suffix=".xlsx",
                    ) as temp_path:
                        logger.info(
                            f"[{mode}] Обработка (скачивание FTP) заняла "
                            f"{time.perf_counter() - io_start:.2f}s: path={path}"
                        )
                        # --- ПАРСИНГ EXCEL (локальный файл) ---
                        parse_start = time.perf_counter()
                        df = pd.read_excel(temp_path, **kwargs)
                        logger.info(
                            f"[{mode}] Парсинг Excel занял "
                            f"{time.perf_counter() - parse_start:.2f}s: "
                            f"rows={len(df)}, cols={df.shape[1]}, path={path}"
                        )
                else:
                    # --- ОБРАБОТКА (открытие удалённого файла) ---
                    io_start = time.perf_counter()
                    with ctx.fs.open(path, "rb") as file_obj:
                        logger.info(
                            f"[{mode}] Обработка (открытие файла) заняла "
                            f"{time.perf_counter() - io_start:.2f}s: path={path}"
                        )
                        # --- ПАРСИНГ EXCEL (сетевой I/O уходит сюда через seek'и) ---
                        parse_start = time.perf_counter()
                        df = pd.read_excel(file_obj, **kwargs)
                        logger.info(
                            f"[{mode}] Парсинг Excel занял "
                            f"{time.perf_counter() - parse_start:.2f}s: "
                            f"rows={len(df)}, cols={df.shape[1]}, path={path}"
                        )
            except (TypeError, ValueError) as exc:
                logger.error(
                    f"[{mode}] Ошибка чтения Excel после "
                    f"{time.perf_counter() - read_start:.2f}s: path={path}, error={exc}"
                )
                if self.dtypes:
                    raise ValueError(
                        f"Failed to read Excel with explicit dtypes {self.dtypes}: {exc}"
                    ) from exc
                raise

            logger.info(
                f"[{mode}] Полный цикл чтения занял "
                f"{time.perf_counter() - read_start:.2f}s: path={path}"
            )
            return self._normalize_dataframe_dtypes(df)

        return self._run_with_timeout(_read_sync, mode=mode, path=path)

    def _read_sample(
        self,
        ctx: FsCtx,
        first_file: str,
        *,
        mode: str,
    ) -> pd.DataFrame:
        return self._read_excel_via_fs(
            ctx,
            first_file,
            mode=mode,
            nrows=self._SAMPLE_ROWS,
        )

    @staticmethod
    def _align_to_meta(
        df: pd.DataFrame,
        *,
        canonical_columns: list[str],
        meta_dtypes: pd.Series,
    ) -> pd.DataFrame:
        df = df.reindex(columns=canonical_columns)

        for column_name, target_dtype in meta_dtypes.items():
            if column_name not in df.columns or str(df[column_name].dtype) == str(target_dtype):
                continue

            dtype_name = str(target_dtype)
            try:
                if dtype_name in {"Int64", "Int32", "Int16", "Int8"} or dtype_name in {
                    "Float64",
                    "Float32",
                    "Float16",
                }:
                    df[column_name] = pd.to_numeric(df[column_name], errors="coerce").astype(
                        dtype_name
                    )
                elif dtype_name in {"boolean", "string"}:
                    df[column_name] = df[column_name].astype(dtype_name)
                elif "datetime64" in dtype_name:
                    df[column_name] = pd.to_datetime(df[column_name], errors="coerce")
                else:
                    df[column_name] = df[column_name].astype(target_dtype)
            except Exception:
                logger.debug(
                    "Failed to align Excel column '{}' to dtype '{}'",
                    column_name,
                    dtype_name,
                )

        return df

    def process(self) -> None:
        runtime = self._get_file_runtime(
            path=self.path,
            timeout_sec=self.read_timeout_sec,
            ftp_block_size=1024 * 1024,
        )
        ctx = runtime.context
        logger.info(f"Loading Excel from {ctx.protocol.upper()}: {ctx.path}")

        try:
            glob_start = time.perf_counter()
            files = runtime.list_files(
                required=True,
                subject="Excel file(s)",
                operation="listing Excel files",
            )
            logger.info(
                f"Листинг файлов (glob) занял {time.perf_counter() - glob_start:.2f}s"
            )
            logger.info(f"Found {len(files)} file(s)")

            sample_start = time.perf_counter()
            with runtime.operation("reading Excel sample", path=files[0]):
                sample = self._read_sample(ctx, files[0], mode="full")
            logger.info(
                f"Чтение сэмпла ({self._SAMPLE_ROWS} строк) заняло "
                f"{time.perf_counter() - sample_start:.2f}s"
            )
            canonical_columns = list(sample.columns)
            meta = sample.iloc[0:0].copy()
            meta_dtypes = meta.dtypes
            logger.debug(f"Canonical columns: {canonical_columns} | dtypes: {dict(meta_dtypes)}")

            def _load_one(path: str) -> pd.DataFrame:
                logger.info(f"[delayed] Начинаю полное чтение файла: {path}")
                with runtime.operation("reading Excel file", path=path):
                    df = self._read_excel_via_fs(ctx, path, mode="full")
                return self._align_to_meta(
                    df,
                    canonical_columns=canonical_columns,
                    meta_dtypes=meta_dtypes,
                )

            delayed_parts = [dask.delayed(_load_one)(file_path) for file_path in files]
            self.output = dd.from_delayed(delayed_parts, meta=meta)
            logger.info(f"Excel loaded (граф построен). Partitions: {self.output.npartitions}")
        except Exception as exc:
            logger.error(f"Error loading Excel from {ctx.path}: {exc}")
            raise

    async def process_metadata(self) -> None:
        metadata = await self.resolve_metadata()
        output_metadata = metadata.get("output")
        if not isinstance(output_metadata, DataFrameMetadata):
            raise TypeError(f"{self.__class__.__name__} expected DataFrameMetadata for output")
        self.output = self.build_empty_ddf_from_metadata(output_metadata)

    def infer_metadata(self) -> NodeMetadata:
        runtime = self._get_file_runtime(
            path=self.path,
            timeout_sec=self.read_timeout_sec,
            ftp_block_size=1024 * 1024,
        )
        ctx = runtime.context
        files = runtime.list_files(
            required=True,
            subject="Excel file(s)",
            operation="listing Excel files for metadata",
        )

        first_file = files[0]
        logger.debug(f"[infer_metadata] using first file: {first_file}")

        try:
            with runtime.operation("reading Excel metadata sample", path=first_file):
                sample = self._read_sample(ctx, first_file, mode="metadata")
        except Exception as exc:
            logger.error(f"[infer_metadata] Failed to read sample from '{first_file}': {exc}")
            raise

        columns_meta: list[Column] = []
        for column_name in sample.columns.tolist():
            series = sample[column_name]
            columns_meta.append(
                Column(
                    name=str(column_name),
                    dtype=DataType.from_type(series.dtype),
                    nullable=bool(sample.empty or series.isna().any()),
                    index=False,
                )
            )

        logger.debug(f"[infer_metadata] inferred {len(columns_meta)} columns")
        return {"output": DataFrameMetadata(columns=columns_meta)}
