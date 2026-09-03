import dask.dataframe as dd
import fsspec
import pandas as pd
import pyarrow as pa
import pytest

from core.types import FsCtx

from src.node_dsl import IO, get_definition
from src.nodes.write.save_parquet import SaveParquet


def _mock_fs_context(protocol="s3", node=None) -> FsCtx:
    """
    Эмулирует возврат FsCtx.
    Формирует путь, избегая схлопывания протокола '://' в ':/'.
    """

    def clean_join(*parts):
        # Соединяем части пути, убирая лишние слэши между ними
        return "/".join(p.strip("/") for p in parts if p and p.strip("/"))

    if protocol == "s3":
        so = {
            "key": "key",
            "secret": "secret",
            "client_kwargs": {"endpoint_url": "http://localhost:9000"},
        }

        bucket = "bucket"
        prefix = "user-space"

        if node:
            inner_path = clean_join(prefix, node._target_path())
            # Добавляем протокол в самом конце
            full_path = f"s3://{bucket}/{inner_path}"
        else:
            full_path = f"s3://{bucket}/{prefix}"

        return FsCtx(
            fs=fsspec.filesystem("s3", **so), protocol="s3", path=full_path, storage_options=so
        )

    if protocol == "ftp":
        so = {
            "host": "localhost",
            "port": 21,
            "user": "user",
            "password": "password",
        }
        initial_dir = "initial_dir"

        if node:
            inner_path = clean_join(initial_dir, node._target_path())
            full_path = f"ftp://localhost:21/{inner_path}"
        else:
            full_path = f"ftp://localhost:21/{initial_dir}"

        return FsCtx(
            fs=fsspec.filesystem("ftp", **so),
            protocol="ftp",
            path=full_path,
            storage_options=so,
            host="localhost",
            port=21,
        )

    raise ValueError(f"Unsupported protocol for test context: {protocol}")


def _build_node(df: dd.DataFrame, **kwargs) -> SaveParquet:
    mode = kwargs.pop("mode", "create")
    compatibility_mode = kwargs.pop("compatibility_mode", "legacy")
    return SaveParquet(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="save-parquet-node",
        connection=object(),  # Заглушка, так как мы мокаем _get_fs_context
        df=df,
        path="reports/dataset.parquet",
        mode=mode,
        compatibility_mode=compatibility_mode,
        **kwargs,
    )


def _capture_to_parquet_call(monkeypatch):
    captured: dict[str, object] = {}

    def _capture_to_parquet(self, path, **kwargs):
        captured["df"] = self
        captured["path"] = path
        captured["kwargs"] = kwargs

    monkeypatch.setattr(dd.DataFrame, "to_parquet", _capture_to_parquet, raising=True)
    return captured


def _assert_name_function(kwargs: dict[str, object]):
    name_function = kwargs["name_function"]
    assert callable(name_function)
    return name_function


def test_save_parquet_single_partition_uses_dataset_name_without_number(monkeypatch):
    ddf = dd.from_pandas(pd.DataFrame({"id": [1, 2]}), npartitions=1)
    node = _build_node(ddf)

    monkeypatch.setattr(node, "_get_fs_context", lambda: _mock_fs_context("s3", node=node))
    captured = _capture_to_parquet_call(monkeypatch)

    node.process()

    name_function = _assert_name_function(captured["kwargs"])
    assert name_function(0) == "dataset.parquet"


def test_save_parquet_multiple_partitions_use_numbered_dataset_names(monkeypatch):
    ddf = dd.from_pandas(pd.DataFrame({"id": [1, 2, 3, 4]}), npartitions=2)
    node = _build_node(ddf)

    monkeypatch.setattr(node, "_get_fs_context", lambda: _mock_fs_context("s3", node=node))
    captured = _capture_to_parquet_call(monkeypatch)

    node.process()

    name_function = _assert_name_function(captured["kwargs"])
    assert name_function(0) == "dataset.00000.parquet"
    assert name_function(1) == "dataset.00001.parquet"


def test_save_parquet_process_applies_row_cap_and_schema_contract(monkeypatch):
    pdf = pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5, 6],
            "name": ["a", "b", "c", "d", "e", "f"],
        }
    )
    ddf = dd.from_pandas(pdf, npartitions=2)
    node = _build_node(
        ddf,
        row_cap=2,
        parquet_types={"id": "int64", "name": "string"},
    )

    # Подменяем получение контекста, передавая инстанс ноды для сборки пути
    monkeypatch.setattr(node, "_get_fs_context", lambda: _mock_fs_context("s3", node=node))
    monkeypatch.setattr(node, "_parquet_dataset_exists", lambda target, storage_options: True)

    captured = _capture_to_parquet_call(monkeypatch)

    node.process()

    # Теперь утверждение пройдет корректно
    assert captured["path"] == "s3://bucket/user-space/reports/dataset.parquet"

    out_df = captured["df"]
    assert isinstance(out_df, dd.DataFrame)
    row_counts = out_df.map_partitions(len).compute().tolist()
    assert sum(row_counts) == len(pdf)
    assert max(row_counts) <= 2

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    schema = kwargs["schema"]
    assert isinstance(schema, dict)
    assert schema["id"] == pa.int64()
    assert schema["name"] == pa.string()
    name_function = _assert_name_function(kwargs)
    assert name_function(0) == "dataset.00000.parquet"
    assert name_function(out_df.npartitions - 1) == "dataset.00003.parquet"


def test_save_parquet_process_raises_for_unknown_contract_column(monkeypatch):
    pdf = pd.DataFrame({"id": [1, 2]})
    ddf = dd.from_pandas(pdf, npartitions=1)
    node = _build_node(ddf, parquet_types={"missing_col": "int64"})

    monkeypatch.setattr(node, "_get_fs_context", lambda: _mock_fs_context("s3", node=node))
    monkeypatch.setattr(node, "_parquet_dataset_exists", lambda target, storage_options: True)

    with pytest.raises(ValueError, match="do not exist in DataFrame"):
        node.process()


def test_save_parquet_process_raises_for_unsupported_parquet_type(monkeypatch):
    pdf = pd.DataFrame({"id": [1, 2]})
    ddf = dd.from_pandas(pdf, npartitions=1)
    node = _build_node(ddf, parquet_types={"id": "unsupported_type"})

    monkeypatch.setattr(node, "_get_fs_context", lambda: _mock_fs_context("s3", node=node))
    monkeypatch.setattr(node, "_parquet_dataset_exists", lambda target, storage_options: True)

    with pytest.raises(ValueError, match="Unsupported parquet type"):
        node.process()


def test_parse_parquet_type_supports_timestamp_with_timezone_and_decimal():
    assert SaveParquet._parse_parquet_type("timestamp[us, tz=UTC]") == pa.timestamp("us", tz="UTC")
    assert SaveParquet._parse_parquet_type("decimal128(18,2)") == pa.decimal128(18, 2)


def test_apply_row_cap_aligns_chunk_dtypes_with_meta_string():
    source_pdf = pd.DataFrame({"DWH_hash_PK": ["a", "b", "c", "d"]})
    source_ddf = dd.from_pandas(source_pdf, npartitions=1)
    string_meta = pd.DataFrame({"DWH_hash_PK": pd.Series(dtype="string")})
    ddf_with_mismatched_runtime_dtype = source_ddf.map_partitions(
        lambda pdf: pdf,
        meta=string_meta,
    )

    node = _build_node(ddf_with_mismatched_runtime_dtype, row_cap=2)
    capped = node._apply_row_cap(ddf_with_mismatched_runtime_dtype)
    result = capped.compute()

    assert capped.npartitions == 2
    assert str(result["DWH_hash_PK"].dtype).startswith("string")


def test_save_parquet_process_falls_back_to_create_when_append_target_is_missing(monkeypatch):
    pdf = pd.DataFrame({"id": [1, 2]})
    ddf = dd.from_pandas(pdf, npartitions=1)
    node = _build_node(ddf, mode="append")

    monkeypatch.setattr(node, "_get_fs_context", lambda: _mock_fs_context("s3", node=node))
    monkeypatch.setattr(node, "_parquet_dataset_exists", lambda target, storage_options: False)
    captured = _capture_to_parquet_call(monkeypatch)

    node.process()

    assert captured["path"] == "s3://bucket/user-space/reports/dataset.parquet"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert "append" not in kwargs
    assert "overwrite" not in kwargs
    assert kwargs["write_metadata_file"] is True
    assert _assert_name_function(kwargs)(0) == "dataset.parquet"


def test_save_parquet_process_keeps_append_when_target_dataset_exists(monkeypatch):
    pdf = pd.DataFrame({"id": [1, 2]})
    ddf = dd.from_pandas(pdf, npartitions=1)
    node = _build_node(ddf, mode="append")

    monkeypatch.setattr(node, "_get_fs_context", lambda: _mock_fs_context("s3", node=node))
    monkeypatch.setattr(node, "_parquet_dataset_exists", lambda target, storage_options: True)
    captured = _capture_to_parquet_call(monkeypatch)

    node.process()

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["append"] is True
    assert kwargs["write_metadata_file"] is None
    assert _assert_name_function(kwargs)(1) == "dataset.00001.parquet"


def test_save_parquet_process_does_not_check_existing_dataset_for_create(monkeypatch):
    pdf = pd.DataFrame({"id": [1, 2]})
    ddf = dd.from_pandas(pdf, npartitions=1)
    node = _build_node(ddf, mode="create")

    monkeypatch.setattr(node, "_get_fs_context", lambda: _mock_fs_context("s3", node=node))
    monkeypatch.setattr(
        node,
        "_parquet_dataset_exists",
        lambda target, storage_options: (_ for _ in ()).throw(AssertionError("unexpected check")),
    )
    captured = _capture_to_parquet_call(monkeypatch)

    node.process()

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert "append" not in kwargs
    assert "overwrite" not in kwargs
    assert kwargs["write_metadata_file"] is True


def test_save_parquet_process_does_not_check_existing_dataset_for_overwrite(monkeypatch):
    pdf = pd.DataFrame({"id": [1, 2]})
    ddf = dd.from_pandas(pdf, npartitions=1)
    node = _build_node(ddf, mode="overwrite")

    monkeypatch.setattr(node, "_get_fs_context", lambda: _mock_fs_context("s3", node=node))
    monkeypatch.setattr(
        node,
        "_parquet_dataset_exists",
        lambda target, storage_options: (_ for _ in ()).throw(AssertionError("unexpected check")),
    )
    captured = _capture_to_parquet_call(monkeypatch)

    node.process()

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["overwrite"] is True
    assert kwargs["write_metadata_file"] is True


def test_save_parquet_process_raises_when_append_dataset_check_returns_non_not_found_error(
    monkeypatch,
):
    pdf = pd.DataFrame({"id": [1, 2]})
    ddf = dd.from_pandas(pdf, npartitions=1)
    node = _build_node(ddf, mode="append")

    monkeypatch.setattr(node, "_get_fs_context", lambda: _mock_fs_context("s3", node=node))
    monkeypatch.setattr(
        node,
        "_parquet_dataset_exists",
        lambda target, storage_options: (_ for _ in ()).throw(
            RuntimeError("broken dataset lookup")
        ),
    )

    with pytest.raises(RuntimeError, match="broken dataset lookup"):
        node.process()


def test_save_parquet_definition_keeps_parquet_types_as_schema_input():
    parquet_types_input = get_definition("SaveParquet").input_definitions["parquet_types"]

    assert parquet_types_input.type == IO.SCHEMA
    assert parquet_types_input.display_type != IO.VARIABLE
    assert parquet_types_input.schema == {
        "type": "object",
        "additionalProperties": {"type": "string"},
        "propertyNames": {"type": "string"},
    }


def test_save_parquet_definition_defaults_to_new_compatibility_mode():
    compatibility_input = get_definition("SaveParquet").input_definitions["compatibility_mode"]

    assert compatibility_input.default == "new"
    assert compatibility_input.is_hidden is True
