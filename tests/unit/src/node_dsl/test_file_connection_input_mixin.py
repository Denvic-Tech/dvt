from types import SimpleNamespace

import dask.dataframe as dd
import pandas as pd
import pytest

from core.types import FsCtx

from src.node_dsl.connection_types import FileConnectionRecord
from src.node_dsl.node_typing import IO
from src.node_dsl.registry import definitions as definitions_registry
from src.nodes.extract.load_csv import LoadCSV
from src.nodes.write.save_csv import SaveCSV


def _expr(value: str) -> dict[str, str]:
    return {
        "__dvt_type": "expr",
        "value": value,
        "expression_kind": "single",
    }


def _make_connection(connection_type: str) -> FileConnectionRecord:
    return FileConnectionRecord(
        SimpleNamespace(
            name=f"{connection_type} connection",
            kind="file",
            type=connection_type,
            driver=None,
            driver_options=None,
            properties={},
            secrets={},
        )
    )


def test_file_connection_definition_exposes_schema_overrides_input():
    definition = definitions_registry._create_node_base_definition(LoadCSV)

    overrides_input = definition.input_definitions["connection_overrides"]

    assert overrides_input.type == IO.SCHEMA
    assert overrides_input.default is None
    assert overrides_input.schema is not None
    assert "oneOf" in overrides_input.schema

    branch_types = {
        branch.get("properties", {}).get("type", {}).get("const")
        or branch.get("properties", {}).get("type", {}).get("default")
        for branch in overrides_input.schema["oneOf"]
    }
    assert {"s3", "ftp", "sftp"}.issubset(branch_types)
    s3_branch = next(
        branch
        for branch in overrides_input.schema["oneOf"]
        if branch.get("properties", {}).get("type", {}).get("const") == "s3"
    )
    assert "verify" in s3_branch["properties"]


@pytest.mark.asyncio
async def test_file_connection_validation_rejects_mismatched_override_branch():
    node = LoadCSV(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-csv-node",
        connection=_make_connection("s3"),
        path="reports/data.csv",
        connection_overrides={
            "type": "ftp",
            "initial_directory": "/incoming",
        },
    )

    with pytest.raises(ValueError, match="does not match connection.type"):
        await node.validate()


@pytest.mark.asyncio
async def test_file_connection_validation_rejects_smb_overrides():
    node = LoadCSV(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-csv-node",
        connection=_make_connection("smbprotocol"),
        path="reports/data.csv",
        connection_overrides={
            "type": "s3",
            "bucket": "other-bucket",
        },
    )

    with pytest.raises(ValueError, match="SMB connections do not support"):
        await node.validate()


def test_get_file_runtime_owns_filesystem_creation(monkeypatch):
    node = LoadCSV(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-csv-node",
        connection=_make_connection("s3"),
        path="reports/data.csv",
    )
    ctx = FsCtx(
        fs=SimpleNamespace(),
        protocol="s3",
        path="s3://bucket/reports/data.csv",
        storage_options={},
        url_root="s3://",
    )
    received_kwargs = {}

    def _get_fs_context(**kwargs):
        received_kwargs.update(kwargs)
        return ctx

    monkeypatch.setattr(node, "_get_fs_context", _get_fs_context)

    runtime = node._get_file_runtime(path=node.path)

    assert runtime.context is ctx
    assert received_kwargs["create_fs"] is False


def test_save_csv_resolves_expression_based_connection_overrides(monkeypatch):
    monkeypatch.setattr(
        "src.node_dsl.runtime.connections.validate_connection_record",
        lambda _record: SimpleNamespace(
            properties=SimpleNamespace(
                bucket="source-bucket",
                region_name="ru-central1",
                endpoint_url="https://s3.local",
                use_ssl=False,
                verify=True,
                path_style=True,
                prefix="source-prefix",
                access_token_id="key",
                access_token_key="secret",
                signature_version=None,
                session_token=None,
            ),
            secrets=SimpleNamespace(
                access_token_id="key",
                access_token_key="secret",
                session_token=None,
            ),
        ),
    )

    node = SaveCSV(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="save-csv-node",
        connection=_make_connection("s3"),
        df=dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
        path="reports/export.csv",
        input_variables={
            "bucket_name": {"name": "bucket_name", "value": "override-bucket"},
            "prefix_name": {"name": "prefix_name", "value": "override-prefix"},
        },
        connection_overrides={
            "type": "s3",
            "bucket": _expr("bucket_name"),
            "prefix": _expr("prefix_name"),
            "verify": False,
        },
    )

    ctx = node._get_fs_context(path=node._target_path(), create_fs=False)

    assert ctx.path == "s3://override-bucket/override-prefix/reports/export.csv"
    assert ctx.storage_options["client_kwargs"]["verify"] is False
