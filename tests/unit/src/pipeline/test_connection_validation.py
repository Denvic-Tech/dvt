from src.node_dsl.core.input_values import NodeInputConstantValue, NodeInputLinkValue
from src.pipeline.validation import validate_pipeline
from src.schemas.internal import NodeData
from src.nodes.connection.get_exist_db_connection import GetExistDBConnection
from src.nodes.connection.get_exist_ftp_connection import GetExistFTPConnection
from src.nodes.connection.get_exist_smb_connection import GetExistSMBConnection
from src.nodes.connection.get_exist_s3_connection import GetExistS3Connection
from src.nodes.extract.load_csv import LoadCSV
from src.nodes.extract.read_query_from_db_v3 import ReadQueryFromDBV3


def _register_nodes(*node_classes) -> None:
    from src.node_dsl.registry import (
        definitions as definitions_registry,
        hooks as hooks_registry,
        nodes as nodes_registry,
    )

    for node_cls in node_classes:
        if node_cls.__name__ not in nodes_registry.get_all():
            nodes_registry.add(node_cls)
        if node_cls.__name__ not in definitions_registry.NODE_DEFINITIONS:
            definitions_registry.build(node_cls)
        hooks_registry.build(node_cls)


def test_validate_pipeline_rejects_ftp_connection_for_sql_input():
    _register_nodes(GetExistFTPConnection, ReadQueryFromDBV3)
    pipeline = {
        "ftp_source": NodeData(
            name="GetExistFTPConnection",
            inputs={"connection_id": NodeInputConstantValue(value=1)},
        ),
        "sql_reader": NodeData(
            name="ReadQueryFromDBV3",
            inputs={
                "connection": NodeInputLinkValue(node_id="ftp_source", output_name="connection"),
                "sql_code": NodeInputConstantValue(value="select 1"),
            },
        ),
    }

    result = validate_pipeline(pipeline)

    assert result.is_valid is False
    assert result.node_errors
    assert "Type mismatch" in result.node_errors["sql_reader"].message


def test_validate_pipeline_rejects_s3_connection_for_sql_input():
    _register_nodes(GetExistS3Connection, ReadQueryFromDBV3)
    pipeline = {
        "s3_source": NodeData(
            name="GetExistS3Connection",
            inputs={"connection_id": NodeInputConstantValue(value=1)},
        ),
        "sql_reader": NodeData(
            name="ReadQueryFromDBV3",
            inputs={
                "connection": NodeInputLinkValue(node_id="s3_source", output_name="connection"),
                "sql_code": NodeInputConstantValue(value="select 1"),
            },
        ),
    }

    result = validate_pipeline(pipeline)

    assert result.is_valid is False
    assert result.node_errors
    assert "Type mismatch" in result.node_errors["sql_reader"].message


def test_validate_pipeline_accepts_s3_connection_for_file_input():
    _register_nodes(GetExistS3Connection, LoadCSV)
    pipeline = {
        "s3_source": NodeData(
            name="GetExistS3Connection",
            inputs={"connection_id": NodeInputConstantValue(value=1)},
        ),
        "csv_loader": NodeData(
            name="LoadCSV",
            inputs={
                "connection": NodeInputLinkValue(node_id="s3_source", output_name="connection"),
                "path": NodeInputConstantValue(value="reports/data.csv"),
            },
        ),
    }

    result = validate_pipeline(pipeline)

    assert result.is_valid is True


def test_validate_pipeline_accepts_smb_connection_for_file_input():
    _register_nodes(GetExistSMBConnection, LoadCSV)
    pipeline = {
        "smb_source": NodeData(
            name="GetExistSMBConnection",
            inputs={"connection_id": NodeInputConstantValue(value=1)},
        ),
        "csv_loader": NodeData(
            name="LoadCSV",
            inputs={
                "connection": NodeInputLinkValue(node_id="smb_source", output_name="connection"),
                "path": NodeInputConstantValue(value="reports/data.csv"),
            },
        ),
    }

    result = validate_pipeline(pipeline)

    assert result.is_valid is True


def test_validate_pipeline_rejects_smb_connection_for_sql_input():
    _register_nodes(GetExistSMBConnection, ReadQueryFromDBV3)
    pipeline = {
        "smb_source": NodeData(
            name="GetExistSMBConnection",
            inputs={"connection_id": NodeInputConstantValue(value=1)},
        ),
        "sql_reader": NodeData(
            name="ReadQueryFromDBV3",
            inputs={
                "connection": NodeInputLinkValue(node_id="smb_source", output_name="connection"),
                "sql_code": NodeInputConstantValue(value="select 1"),
            },
        ),
    }

    result = validate_pipeline(pipeline)

    assert result.is_valid is False
    assert result.node_errors
    assert "Type mismatch" in result.node_errors["sql_reader"].message


def test_validate_pipeline_accepts_db_connection_for_sql_input():
    _register_nodes(GetExistDBConnection, ReadQueryFromDBV3)
    pipeline = {
        "db_source": NodeData(
            name="GetExistDBConnection",
            inputs={"connection_id": NodeInputConstantValue(value=1)},
        ),
        "sql_reader": NodeData(
            name="ReadQueryFromDBV3",
            inputs={
                "connection": NodeInputLinkValue(node_id="db_source", output_name="connection"),
                "sql_code": NodeInputConstantValue(value="select 1"),
            },
        ),
    }

    result = validate_pipeline(pipeline)

    assert result.is_valid is True
