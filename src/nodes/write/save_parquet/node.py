import posixpath as ppath
import re
from collections.abc import Callable
from functools import partial
from typing import Literal

import dask
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as pa_ds
from dask import dataframe as dd
from dask.dataframe.io.parquet.core import get_engine
from loguru import logger

from core.parquet.write import ParquetWriteRequest, write_dataframe

from src.node_dsl import BaseNode, InputField
from src.node_dsl.runtime.integrations.file_connection.filesystem import FileConnectionRuntime
from src.node_dsl.runtime.integrations.file_connection.mixin import FileConnectionInputMixin
from src.nodes.write._shared.target_path import normalize_relative_target_path


def _parquet_part_name(part_index: int, *, dataset_stem: str, single_file: bool) -> str:
    if single_file:
        return f"{dataset_stem}.parquet"
    return f"{dataset_stem}.{part_index:05d}.parquet"


class SaveParquet(FileConnectionInputMixin, BaseNode):
    TITLE = "Save Parquet"
    EMOJI = "💾"
    CATEGORY = "Writing"
    OUTPUT_NODE = True

    _DECIMAL_RE = re.compile(
        r"^decimal(?P<bits>128|256)\((?P<p>\d+)\s*,\s*(?P<s>\d+)\)$", re.IGNORECASE
    )
    _TIMESTAMP_RE = re.compile(
        r"^timestamp\[(?P<unit>s|ms|us|ns)(?:,\s*tz=(?P<tz>[^\]]+))?\]$",
        re.IGNORECASE,
    )
    _TIME32_RE = re.compile(r"^time32\[(?P<unit>s|ms)\]$", re.IGNORECASE)
    _TIME64_RE = re.compile(r"^time64\[(?P<unit>us|ns)\]$", re.IGNORECASE)

    # --- Inputs ---
    df: dd.DataFrame = InputField()

    path: str = InputField(
        description="Относительный путь к parquet dataset, например: reports/2025-09/data.parquet"
    )

    mode: Literal["create", "overwrite", "append"] = InputField(description="Режим записи")

    # параметры записи
    compression: Literal["snappy", "gzip", "brotli", "zstd", "lz4", "none"] = InputField(
        default="snappy", description="Кодек сжатия parquet"
    )

    write_index: bool = InputField(
        default=False, description="Сохранять индекс DataFrame как колонку"
    )

    partition_on: list[str] | None = InputField(
        default=None, is_hidden=True, description="Список колонок для Hive-partitioning"
    )

    row_cap: int | None = InputField(
        default=None,
        min_value=1,
        description="Максимум строк в одном parquet-файле (режим row-cap)",
    )

    filename_template: str | None = InputField(
        default=None,
        is_hidden=True,
        description=(
            "Шаблон имени physical parquet-файлов в Advanced layout. "
            "Поддерживаются <partition_index>, <increment>, <uuid>."
        ),
    )

    compatibility_mode: Literal["legacy", "new"] = InputField(
        default="new",
        is_hidden=True,
        allow_variables=False,
        allow_expressions=False,
    )

    parquet_types: dict[str, str] | None = InputField(
        default=None, description="Жесткий parquet-контракт: {column_name: parquet_type}"
    )

    def _target_path(self) -> str:
        return normalize_relative_target_path(self.path, ".parquet")

    def _name_function(self, *, single_file: bool) -> Callable[[int], str]:
        dataset_name = ppath.basename(self._target_path())
        dataset_stem = dataset_name.removesuffix(".parquet")
        return partial(
            _parquet_part_name,
            dataset_stem=dataset_stem,
            single_file=single_file,
        )

    def _get_fs_context(self):
        return super()._get_fs_context(path=self._target_path(), create_fs=False)

    def _resolve_target_filesystem(
        self, target: str, storage_options: dict | None
    ) -> tuple[object, str]:
        engine = get_engine("pyarrow")
        fs, paths, _, _ = engine.extract_filesystem(
            target,
            filesystem=None,
            dataset_options={},
            open_file_options={},
            storage_options=storage_options,
        )
        if len(paths) != 1:
            raise ValueError(f"Expected one parquet target path, got {len(paths)} for {target}")
        return fs, paths[0]

    def _parquet_dataset_exists(self, target: str, storage_options: dict | None) -> bool:
        fs, normalized_target = self._resolve_target_filesystem(target, storage_options)
        try:
            pa_ds.dataset(
                normalized_target,
                filesystem=getattr(fs, "fs", fs),
                format="parquet",
            )
        except FileNotFoundError:
            return False
        return True

    @staticmethod
    def _parquet_write_kwargs(mode: Literal["create", "overwrite", "append"]) -> dict:
        if mode == "overwrite":
            return {"overwrite": True}

        if mode == "append":
            return {"append": True}

        if mode == "create":
            return {}

        raise ValueError(f"Unknown mode: {mode}")

    @classmethod
    def _parse_parquet_type(cls, parquet_type: str) -> pa.DataType:
        raw = parquet_type.strip()
        lowered = raw.lower()
        if not lowered:
            raise ValueError("Parquet type cannot be empty.")

        decimal_match = cls._DECIMAL_RE.fullmatch(lowered)
        if decimal_match:
            precision = int(decimal_match.group("p"))
            scale = int(decimal_match.group("s"))
            bits = decimal_match.group("bits")
            if bits == "128":
                return pa.decimal128(precision, scale)
            return pa.decimal256(precision, scale)

        timestamp_match = cls._TIMESTAMP_RE.fullmatch(raw)
        if timestamp_match:
            unit = timestamp_match.group("unit").lower()
            tz = timestamp_match.group("tz")
            return pa.timestamp(unit, tz=tz)

        time32_match = cls._TIME32_RE.fullmatch(lowered)
        if time32_match:
            return pa.time32(time32_match.group("unit"))

        time64_match = cls._TIME64_RE.fullmatch(lowered)
        if time64_match:
            return pa.time64(time64_match.group("unit"))

        try:
            return pa.type_for_alias(lowered)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported parquet type '{raw}'. "
                f"Examples: int64, string, timestamp[ns], timestamp[us, tz=UTC], "
                f"decimal128(18,2)."
            ) from exc

    def _build_schema_contract(self, ddf: dd.DataFrame) -> str | dict[str, pa.DataType]:
        if not self.parquet_types:
            return "infer"

        if not isinstance(self.parquet_types, dict):
            raise TypeError(
                "Input 'parquet_types' must be a dictionary {column_name: parquet_type}."
            )

        schema_contract: dict[str, pa.DataType] = {}
        df_columns = set(map(str, ddf.columns))
        unknown_columns = sorted(set(self.parquet_types) - df_columns)
        if unknown_columns:
            raise ValueError(
                f"Columns from parquet contract do not exist in DataFrame: {unknown_columns}"
            )

        for column_name, parquet_type in self.parquet_types.items():
            if not isinstance(parquet_type, str):
                raise TypeError(
                    f"Parquet type for column '{column_name}' must be string, got {type(parquet_type)}"
                )
            schema_contract[column_name] = self._parse_parquet_type(parquet_type)

        return schema_contract

    @staticmethod
    def _slice_partition(
        pdf: pd.DataFrame,
        start: int,
        stop: int,
        expected_dtypes: dict[str, object] | None = None,
    ) -> pd.DataFrame:
        chunk = pdf.iloc[start:stop].copy()
        if not expected_dtypes:
            return chunk

        for column, target_dtype in expected_dtypes.items():
            if column not in chunk.columns:
                continue
            if chunk[column].dtype == target_dtype:
                continue
            try:
                chunk[column] = chunk[column].astype(target_dtype)
            except (TypeError, ValueError):
                # Keep source dtype if cast is not possible for this chunk.
                continue
        return chunk

    def _apply_row_cap(self, ddf: dd.DataFrame) -> dd.DataFrame:
        if self.row_cap is None:
            return ddf

        row_cap = int(self.row_cap)
        if row_cap < 1:
            raise ValueError("Input 'row_cap' must be >= 1.")

        partition_lengths = ddf.map_partitions(len).compute()
        delayed_parts = list(ddf.to_delayed())
        delayed_chunks = []
        expected_dtypes = dict(ddf._meta.dtypes.items())
        for delayed_part, partition_length in zip(delayed_parts, partition_lengths, strict=True):
            resolved_partition_length = int(partition_length)
            for start in range(0, resolved_partition_length, row_cap):
                delayed_chunks.append(
                    dask.delayed(self._slice_partition)(
                        delayed_part,
                        start,
                        start + row_cap,
                        expected_dtypes,
                    )
                )

        if not delayed_chunks:
            return ddf

        return dd.from_delayed(delayed_chunks, meta=ddf._meta)

    def _process_legacy(self):
        ctx = self._get_fs_context()
        target = ctx.path
        requested_mode = self.mode
        effective_mode = requested_mode

        if requested_mode == "append" and not self._parquet_dataset_exists(
            target, ctx.storage_options
        ):
            effective_mode = "create"
            logger.warning(
                f"Parquet dataset not found for append mode, falling back to create: "
                f"{target} (requested_mode={requested_mode})"
            )

        partition_on = self.partition_on
        if requested_mode == "append" and isinstance(partition_on, list) and len(partition_on) == 0:
            partition_on = None

        ddf_to_write = self._apply_row_cap(self.df)
        schema_contract = self._build_schema_contract(ddf_to_write)
        single_file = effective_mode != "append" and ddf_to_write.npartitions == 1

        logger.info(
            f"Saving DataFrame to Parquet: {target} "
            f"(mode={requested_mode}, effective_mode={effective_mode}, "
            f"compression={self.compression}, write_index={self.write_index}, "
            f"partition_on={partition_on}, row_cap={self.row_cap}, "
            f"schema_contract_columns={list(self.parquet_types.keys()) if self.parquet_types else []})"
        )

        try:
            kwargs = {
                "engine": "pyarrow",
                "compression": None if self.compression == "none" else self.compression,
                "write_index": self.write_index,
                "partition_on": partition_on,
                # In append mode, let Dask update _metadata only when a complete
                # metadata file already exists. Forcing True would create a new
                # _metadata containing only the appended batch when it is absent.
                "write_metadata_file": None if effective_mode == "append" else True,
                "storage_options": ctx.storage_options,
                "schema": schema_contract,
                "name_function": self._name_function(single_file=single_file),
            }
            kwargs.update(self._parquet_write_kwargs(effective_mode))

            # Dask создаст каталог <path>.parquet/ и положит туда именованные parquet-части.
            # Если включен row_cap, каждая dask-партиция будет <= row_cap строк.
            ddf_to_write.to_parquet(target, **kwargs)

            logger.info(
                f"DataFrame saved successfully "
                f"(npartitions={ddf_to_write.npartitions}, mode={requested_mode}, "
                f"effective_mode={effective_mode})."
            )

        except Exception as e:
            logger.error(f"Error saving DataFrame to Parquet at {target}: {e}")
            raise

    def _new_request(self) -> ParquetWriteRequest:
        return ParquetWriteRequest(
            path=self.path,
            mode=self.mode,
            filename_template=self.filename_template,
            row_cap=self.row_cap,
            partition_on=self.partition_on,
            compression=self.compression,
            write_index=self.write_index,
            parquet_types=self.parquet_types,
        )

    def _new_target_path(self, request: ParquetWriteRequest) -> str:
        if request.layout.value == "simple":
            return normalize_relative_target_path(self.path, ".parquet")
        return (self.path or "").strip().replace("\\", "/").strip("/")

    def _process_new(self) -> None:
        request = self._new_request()
        target_path = self._new_target_path(request)
        ctx = super()._get_fs_context(path=target_path, create_fs=False)
        runtime = FileConnectionRuntime(ctx)

        logger.info(
            f"Saving DataFrame to Parquet with write_v1: {ctx.path} "
            f"(layout={request.layout.value}, mode={request.normalized_mode.value}, "
            f"filename_template={self.filename_template!r}, row_cap={self.row_cap}, "
            f"partition_on={self.partition_on}, compression={self.compression}, "
            f"write_index={self.write_index})"
        )

        with runtime.operation("writing Parquet data", path=ctx.path):
            result = write_dataframe(self.df, ctx, request)

        logger.info(
            f"DataFrame saved successfully with write_v1 "
            f"(layout={result.layout.value}, rows={result.rows_written}, "
            f"files={result.files_written})."
        )

    def process(self):
        if self.compatibility_mode == "legacy":
            return self._process_legacy()
        return self._process_new()
