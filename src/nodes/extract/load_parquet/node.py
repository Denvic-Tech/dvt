from urllib.parse import unquote

import dask
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as pa_ds
import pyarrow.fs as pa_fs
import pyarrow.parquet as pq
from dask import dataframe as dd
from loguru import logger

from core.parquet.write.dask import mark_source_path_arg
from core.parquet.write.filesystem import ParquetFilesystem
from core.parquet.write.partitioning import partition_value_type
from core.parquet.write.schema import stored_dataset_schema_from_arrow
from core.types import Column, DataFrameMetadata, DataType

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.runtime.integrations.file_connection.mixin import FileConnectionInputMixin
from src.node_dsl.types import NodeMetadata
from src.nodes.extract._shared.ftp_file import localized_ftp_file


@mark_source_path_arg(0)
def _read_ftp_parquet_file(
    path: str,
    storage_options: dict,
    *,
    columns: list[str] | None,
    hive_values: dict[str, object] | None = None,
    meta: pd.DataFrame | None = None,
) -> pd.DataFrame:
    with localized_ftp_file(
        path,
        storage_options,
        prefix="load-parquet-ftp-",
        default_suffix=".parquet",
    ) as temp_path:
        physical_columns = columns
        if columns and hive_values:
            physical_columns = [column for column in columns if column not in hive_values]
        pdf = pd.read_parquet(temp_path, engine="pyarrow", columns=physical_columns)
        for column, value in (hive_values or {}).items():
            if columns is None or column in columns:
                pdf[column] = value
        if columns is not None:
            pdf = pdf[[column for column in columns if column in pdf.columns]]
        if meta is not None:
            dtype_map = {
                column: dtype
                for column, dtype in meta.dtypes.items()
                if column in pdf.columns
            }
            if dtype_map:
                pdf = pdf.astype(dtype_map)
        return pdf


def _decode_hive_value(raw_value: str) -> str | None:
    value = unquote(raw_value)
    if value == "__HIVE_DEFAULT_PARTITION__":
        return None
    return value


def _extract_hive_values(root: str, file_path: str) -> dict[str, str | None]:
    root = root.rstrip("/")
    relative = file_path[len(root) :].lstrip("/") if file_path.startswith(root) else file_path
    result: dict[str, str | None] = {}
    for segment in relative.split("/")[:-1]:
        if "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        if key:
            result[key] = _decode_hive_value(value)
    return result


def _list_ftp_parquet_files(runtime) -> list[tuple[str, dict[str, str | None]]]:
    ctx = runtime.context
    raw_root = runtime.strip_protocol_path()
    try:
        info = ctx.fs.info(raw_root)
    except FileNotFoundError:
        runtime.raise_missing(operation="listing Parquet files", subject="Parquet file(s)")

    if info.get("type") != "directory":
        if not raw_root.lower().endswith(".parquet"):
            raise ValueError(
                f"FTP Parquet target is not a .parquet file or dataset directory: {ctx.path}"
            )
        return [(ctx.path, {})]

    try:
        found = ctx.fs.find(raw_root, withdirs=False)
    except TypeError:
        found = ctx.fs.find(raw_root)
    if isinstance(found, dict):
        found = list(found)
    parquet_files = sorted(str(path) for path in found if str(path).lower().endswith(".parquet"))
    if not parquet_files:
        runtime.raise_missing(operation="listing Parquet files", subject="Parquet file(s)")
    return [
        (runtime.restore_url(path), _extract_hive_values(raw_root, str(path)))
        for path in parquet_files
    ]


def _read_parquet_schema(fs, path: str) -> pa.Schema:
    raw_path = fs._strip_protocol(path) if hasattr(fs, "_strip_protocol") else path
    with fs.open(raw_path, "rb") as handle:
        return pq.ParquetFile(handle).schema_arrow


def _partition_schema_from_stored(
    stored_schema,
    hive_column_names: tuple[str, ...],
) -> pa.Schema:
    if stored_schema.logical is not None and stored_schema.partition_on is not None:
        fields = [stored_schema.logical.field(column) for column in stored_schema.partition_on]
        return pa.schema(fields)
    return pa.schema([pa.field(column, pa.string()) for column in hive_column_names])


def _cast_hive_values(
    raw_values: dict[str, str | None],
    partition_schema: pa.Schema,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for column, raw_value in raw_values.items():
        field = partition_schema.field(column)
        if raw_value is None:
            result[column] = None
        else:
            result[column] = pc.cast(
                pa.scalar(raw_value), partition_value_type(field.type), safe=True
            ).as_py()
    return result


def _meta_from_logical_schema(
    logical_schema: pa.Schema,
    columns: list[str] | None,
    *,
    category_values: dict[str, list[object]] | None = None,
) -> pd.DataFrame:
    selected = logical_schema
    if columns is not None:
        missing = sorted(set(columns) - set(logical_schema.names))
        if missing:
            raise ValueError(f"Columns not found in Parquet dataset: {missing}")
        selected = pa.schema([logical_schema.field(column) for column in columns])
    meta = selected.empty_table().to_pandas()
    for column, values in (category_values or {}).items():
        if column in meta.columns:
            meta[column] = pd.Series(
                pd.Categorical([], categories=values),
                index=meta.index,
                name=column,
            )
    return meta


def _dvt_partitioning_options(
    ctx,
) -> tuple[dict | None, dict[str, pd.CategoricalDtype]]:
    filesystem = ParquetFilesystem(ctx)
    parquet_files = filesystem.list_parquet_files(filesystem.target)
    if not parquet_files:
        return None, {}
    stored = stored_dataset_schema_from_arrow(_read_parquet_schema(ctx.fs, parquet_files[0]))
    if not stored.partition_on or stored.logical is None:
        return None, {}
    partition_schema = pa.schema([stored.logical.field(column) for column in stored.partition_on])
    dictionary_fields = [field for field in partition_schema if pa.types.is_dictionary(field.type)]
    if not dictionary_fields:
        return {"partitioning": {"flavor": "hive", "schema": partition_schema}}, {}

    partitioning_factory = pa_ds.HivePartitioning.discover(
        infer_dictionary=True,
        schema=partition_schema,
    )
    arrow_filesystem = pa_fs.PyFileSystem(pa_fs.FSSpecHandler(ctx.fs))
    discovered_dataset = pa_ds.dataset(
        filesystem.target,
        filesystem=arrow_filesystem,
        format="parquet",
        partitioning=partitioning_factory,
    )
    discovered_partitioning = discovered_dataset.partitioning
    category_dtypes: dict[str, pd.CategoricalDtype] = {}
    dictionary_by_name = dict(
        zip(discovered_partitioning.schema.names, discovered_partitioning.dictionaries, strict=True)
    )
    for field in dictionary_fields:
        dictionary = dictionary_by_name[field.name]
        category_dtypes[field.name] = pd.CategoricalDtype(categories=dictionary.to_pylist())

    # Feeding dictionary Hive fields directly into Dask makes PyArrow construct a
    # per-file [None] category for NULL partitions. Read scalar partition values
    # first, then apply the dataset-wide inferred categories lazily below.
    read_partition_schema = pa.schema(
        [
            pa.field(
                field.name,
                partition_value_type(field.type),
                nullable=field.nullable,
                metadata=field.metadata,
            )
            for field in partition_schema
        ]
    )
    return {
        "partitioning": {"flavor": "hive", "schema": read_partition_schema}
    }, category_dtypes


class LoadParquet(FileConnectionInputMixin, DFOutputBaseNode):
    TITLE = "Load Parquet"
    EMOJI = "🧱"
    CATEGORY = "Extraction"

    # --- Inputs ---
    path: str = InputField(
        description="Путь в формате s3://bucket/user_id/<path>.parquet (задавай относительный path)"
    )

    # Ограничим набор колонок (пробрасывается в pushdown на стороне parquet)
    usecols: list[str] | None = InputField(is_hidden=True)

    # --- Outputs ---
    output: dd.DataFrame = OutputField()

    def _read_parquet(self) -> dd.DataFrame:
        runtime = self._get_file_runtime(path=self.path)
        ctx = runtime.context

        if ctx.protocol == "ftp":
            ftp_files = _list_ftp_parquet_files(runtime)
            first_path, first_raw_hive_values = ftp_files[0]
            first_physical_schema = _read_parquet_schema(ctx.fs, first_path)
            stored_schema = stored_dataset_schema_from_arrow(first_physical_schema)
            hive_columns = tuple(first_raw_hive_values)
            partition_schema = _partition_schema_from_stored(stored_schema, hive_columns)
            logical_schema = stored_schema.logical
            if logical_schema is None:
                logical_schema = pa.schema(
                    [*first_physical_schema, *partition_schema]
                )
            category_values: dict[str, list[object]] = {}
            for field in partition_schema:
                if not pa.types.is_dictionary(field.type):
                    continue
                values: list[object] = []
                for _path, raw_hive_values in ftp_files:
                    raw_value = raw_hive_values.get(field.name)
                    if raw_value is None:
                        continue
                    value = pc.cast(
                        pa.scalar(raw_value),
                        partition_value_type(field.type),
                        safe=True,
                    ).as_py()
                    if value not in values:
                        values.append(value)
                category_values[field.name] = values
            meta = _meta_from_logical_schema(
                logical_schema,
                self.usecols,
                category_values=category_values,
            )
            delayed_parts = [
                dask.delayed(_read_ftp_parquet_file)(
                    path,
                    dict(ctx.storage_options),
                    columns=self.usecols,
                    hive_values=_cast_hive_values(raw_hive_values, partition_schema),
                    meta=meta,
                )
                for path, raw_hive_values in ftp_files
            ]
            return dd.from_delayed(delayed_parts, meta=meta)

        runtime.list_files(
            required=True,
            subject="Parquet file(s)",
            operation="listing Parquet files",
        )

        # dtypes вытягиваются из footer, это очень дёшево
        with runtime.operation("reading Parquet files"):
            dataset_options, category_dtypes = _dvt_partitioning_options(ctx)
            read_kwargs = {
                "engine": "pyarrow",
                "columns": self.usecols,
                "storage_options": ctx.storage_options,
                "gather_statistics": "auto",
            }
            if dataset_options is not None:
                read_kwargs["dataset"] = dataset_options
            result = dd.read_parquet(ctx.path, **read_kwargs)
            selected_category_dtypes = {
                column: dtype
                for column, dtype in category_dtypes.items()
                if self.usecols is None or column in self.usecols
            }
            if selected_category_dtypes:
                result = result.astype(selected_category_dtypes)
            return result

    def process(self) -> None:
        logger.info(f"Loading Parquet from: {self.path}")
        try:
            self.output = self._read_parquet()
            # Не триггерим compute, просто логируем известные атрибуты
            logger.info(f"Parquet loaded (npartitions={self.output.npartitions})")
        except FileNotFoundError as exc:
            logger.error(f"Parquet file not found at {self.path}: {exc}")
            raise
        except Exception as e:
            logger.error(f"Error loading Parquet from {self.path}: {e}")
            raise

    def infer_metadata(self) -> NodeMetadata:
        try:
            logger.info(f"Infer metadata for Parquet: {self.path}")

            ddf = self._read_parquet()

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

            return {"output": DataFrameMetadata(columns=columns)}

        except Exception as e:
            logger.error(f"Error inferring metadata for Parquet {self.path}: {e}")
            raise
