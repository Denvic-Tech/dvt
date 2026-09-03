from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import zipfile
from typing import Any

import sqlalchemy as sa
import sqlglot
from db_connection.domain import ConnectionListQuery
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlglot import exp

from services.gateway.deps.db_catalog import build_catalog_actor, get_catalog_use_cases
from services.gateway.deps.db_connection import get_connection_service
from services.gateway.deps.dvt_service_files import (
    _root_prefix,
    build_dvt_service_files_storage,
)
from services.gateway.routes.storage.deps.impl import get_file_storage_facade

from src.crud import graph as graph_crud
from src.db import async_engine
from src.modules.db_connection import build_resolve_connection_client_use_case
from src.modules.file_storage.domain.entities import StorageFileNode
from src.modules.file_storage.domain.value_objects import StorageRelativePath
from src.modules.user.infra.repositories import SQLAlchemyUserRepository
from src.node_dsl.core.input_values import parse_node_input_value

import config

from .access import (
    connection_public_payload,
    get_accessible_connection,
    get_accessible_project,
    is_excluded_connection,
    list_accessible_projects,
    sanitized_mapping,
)
from .auth import MCPPrincipal
from .errors import AIMCPHTTPError
from .pagination import decode_cursor, encode_cursor


def _catalog_meta(response) -> dict[str, Any]:
    return {
        "catalog_version": response.catalog_version,
        "loaded_at": response.loaded_at.isoformat(),
        "expires_at": response.expires_at.isoformat(),
        "cache_status": response.cache_status.value,
        "dialect": response.dialect,
    }


async def list_connections(
    *,
    session,
    principal: MCPPrincipal,
    kind: str | None = None,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    query = ConnectionListQuery(kind=kind, name=search, include_deleted=False)
    connections = await get_connection_service().list(query, actor=principal.user)
    allowed = [
        item
        for item in connections
        if not is_excluded_connection(item) and principal.allows_connection(item.id)
    ]
    items = [connection_public_payload(item) for item in allowed]
    projects = await list_accessible_projects(session, principal)
    for project in projects:
        nodes, _, _ = await graph_crud.get_graph_by(session, project_id=project.id)
        for node in nodes:
            for input_name, value in (node.input_values or {}).items():
                parsed = parse_node_input_value(value)
                raw = None if parsed is None else parsed.model_dump(by_alias=True).get("value")
                if not isinstance(raw, dict) or raw.get("type") != "dvt_service_files":
                    continue
                connection_id = raw.get("id")
                properties = raw.get("properties")
                expected_id = f"dvt-service-files:{project.id}:{node.ui_id}:{input_name}"
                if (
                    connection_id != expected_id
                    or not isinstance(properties, dict)
                    or properties.get("project_id") != project.id
                ):
                    continue
                items.append(
                    {
                        "id": connection_id,
                        "name": str(raw.get("name") or "DVT service files"),
                        "kind": "file",
                        "type": "dvt_service_files",
                        "driver": None,
                        "properties": sanitized_mapping(raw.get("properties") or {}),
                        "labels": {},
                        "metadata": sanitized_mapping(raw.get("metadata") or {}),
                        "capabilities": {
                            "database_catalog": False,
                            "ddl_create": False,
                            "readonly_sql": False,
                            "storage_list": True,
                            "storage_preview": True,
                        },
                        "updated_at": project.updated_at.isoformat(),
                    }
                )
    deduplicated = {item["id"]: item for item in items}
    items = sorted(deduplicated.values(), key=lambda item: (item["name"].lower(), item["id"]))
    if kind:
        items = [item for item in items if item["kind"].lower() == kind.lower()]
    if search:
        items = [item for item in items if search.lower() in item["name"].lower()]
    offset = decode_cursor(cursor)
    limit = max(1, min(limit, 200))
    page = items[offset : offset + limit]
    return {
        "items": page,
        "next_cursor": encode_cursor(offset + len(page), len(items)),
    }


async def get_connection(*, session, principal: MCPPrincipal, connection_id: str) -> dict[str, Any]:
    dvt_context = await _dvt_service_files_context(
        session=session,
        principal=principal,
        connection_id=connection_id,
    )
    if dvt_context is not None:
        project, _, _, raw = dvt_context
        return {
            "id": connection_id,
            "name": str(raw.get("name") or "DVT service files"),
            "kind": "file",
            "type": "dvt_service_files",
            "driver": None,
            "properties": sanitized_mapping(raw.get("properties") or {}),
            "labels": {},
            "metadata": sanitized_mapping(raw.get("metadata") or {}),
            "capabilities": {
                "database_catalog": False,
                "ddl_create": False,
                "readonly_sql": False,
                "storage_list": True,
                "storage_preview": True,
            },
            "updated_at": project.updated_at.isoformat(),
        }
    return connection_public_payload(await get_accessible_connection(principal, connection_id))


async def _dvt_service_files_context(*, session, principal: MCPPrincipal, connection_id: str):
    if not connection_id.startswith("dvt-service-files:"):
        return None
    parts = connection_id.split(":", 3)
    if len(parts) != 4:
        raise AIMCPHTTPError(404, "CONNECTION_NOT_FOUND_OR_DENIED", "Connection is unavailable.")
    _, project_id, expected_node_id, expected_input_name = parts
    project = await get_accessible_project(session, principal, project_id)
    nodes, _, _ = await graph_crud.get_graph_by(session, project_id=project.id)
    for node in nodes:
        if node.ui_id != expected_node_id:
            continue
        value = (node.input_values or {}).get(expected_input_name)
        parsed = parse_node_input_value(value)
        raw = None if parsed is None else parsed.model_dump(by_alias=True).get("value")
        properties = raw.get("properties") if isinstance(raw, dict) else None
        if (
            isinstance(raw, dict)
            and raw.get("id") == connection_id
            and raw.get("type") == "dvt_service_files"
            and isinstance(properties, dict)
            and properties.get("organization_id") == project.organization_id
            and properties.get("project_id") == project.id
            and properties.get("root_prefix") == _root_prefix(node.ui_id, expected_input_name)
        ):
            return project, node.ui_id, expected_input_name, raw
    raise AIMCPHTTPError(404, "CONNECTION_NOT_FOUND_OR_DENIED", "Connection is unavailable.")


async def browse_database(
    *,
    principal: MCPPrincipal,
    redis,
    connection_id: str,
    level: str,
    database_name: str | None = None,
    schema_name: str | None = None,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    connection = await get_accessible_connection(principal, connection_id)
    if str(connection.kind).lower() != "sql":
        raise AIMCPHTTPError(422, "CONNECTION_NOT_FOUND_OR_DENIED", "Connection is not SQL.")
    use_cases = get_catalog_use_cases(redis)
    actor = build_catalog_actor(principal.user)
    limit = max(1, min(limit, 200))
    if level == "databases":
        response = await use_cases.list_databases.execute(
            connection_id=connection_id,
            actor=actor,
            search=search,
            cursor=cursor,
            limit=limit,
        )
        items = [
            {"name": item.name, "is_current": item.is_current} for item in response.result.items
        ]
    elif level == "schemas":
        response = await use_cases.list_schemas.execute(
            connection_id=connection_id,
            actor=actor,
            database_name=database_name,
            search=search,
            cursor=cursor,
            limit=limit,
        )
        items = [
            {"name": item.name, "database_name": item.database_name}
            for item in response.result.items
        ]
    elif level == "tables":
        response = await use_cases.list_tables.execute(
            connection_id=connection_id,
            actor=actor,
            database_name=database_name,
            schema_name=schema_name,
            search=search,
            cursor=cursor,
            limit=limit,
        )
        items = [
            {
                "name": item.name,
                "kind": item.kind.value,
                "database_name": item.database_name,
                "schema_name": item.schema_name,
            }
            for item in response.result.items
        ]
    else:
        raise AIMCPHTTPError(
            422, "GRAPH_VALIDATION_FAILED", "level must be databases, schemas, or tables."
        )
    return {
        "items": items,
        "next_cursor": response.result.next_cursor,
        "meta": _catalog_meta(response),
    }


async def get_database_table(
    *,
    principal: MCPPrincipal,
    redis,
    connection_id: str,
    table_name: str,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> dict[str, Any]:
    connection = await get_accessible_connection(principal, connection_id)
    if str(connection.kind).lower() != "sql":
        raise AIMCPHTTPError(422, "CONNECTION_NOT_FOUND_OR_DENIED", "Connection is not SQL.")
    response = await get_catalog_use_cases(redis).get_table.execute(
        connection_id=connection_id,
        actor=build_catalog_actor(principal.user),
        database_name=database_name,
        schema_name=schema_name,
        table_name=table_name,
    )
    table = response.result.table
    if table is None:
        raise AIMCPHTTPError(404, "CONNECTION_NOT_FOUND_OR_DENIED", "Table was not found.")
    return {
        "item": {
            "name": table.name,
            "kind": table.kind.value,
            "database_name": table.database_name,
            "schema_name": table.schema_name,
            "columns": [
                {
                    "name": column.name,
                    "ordinal": column.ordinal,
                    "dtype": column.dtype,
                    "nullable": column.nullable,
                    "indexed": column.indexed,
                    "primary_key": column.primary_key,
                    "indexes": list(column.indexes),
                }
                for column in table.columns
            ],
        },
        "meta": _catalog_meta(response),
    }


def _parse_readonly_sql(sql: str, dialect: str | None) -> tuple[str, bool]:
    source = sql.strip().rstrip(";").strip()
    if not source:
        raise AIMCPHTTPError(422, "UNSAFE_SQL", "SQL query is empty.")
    is_explain = source[:7].upper() == "EXPLAIN"
    parse_source = source
    if is_explain:
        remainder = source[7:].strip()
        if re.search(r"\bANALY[ZS]E\b", remainder, flags=re.IGNORECASE):
            raise AIMCPHTTPError(422, "UNSAFE_SQL", "EXPLAIN ANALYZE is not allowed.")
        if not remainder.upper().startswith(("SELECT", "WITH")):
            raise AIMCPHTTPError(
                422,
                "UNSAFE_SQL",
                "Only plain EXPLAIN SELECT/WITH is allowed.",
            )
        parse_source = remainder
    try:
        statements = sqlglot.parse(parse_source, read=dialect or None)
    except Exception as exc:
        raise AIMCPHTTPError(422, "UNSAFE_SQL", "SQL query could not be parsed.") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise AIMCPHTTPError(422, "UNSAFE_SQL", "Only one read-only SELECT/WITH query is allowed.")
    statement = statements[0]
    forbidden = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Create,
        exp.Drop,
        exp.Alter,
        exp.Merge,
        exp.Command,
        exp.Copy,
        exp.Lock,
        exp.Into,
    )
    if any(statement.find(item) is not None for item in forbidden):
        raise AIMCPHTTPError(422, "UNSAFE_SQL", "SQL query contains a forbidden operation.")
    return source, is_explain


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return f"<binary:{len(value)} bytes>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _bounded_result(result, max_rows: int) -> tuple[list[str], list[dict[str, Any]], bool]:
    columns = list(result.keys())
    rows = result.fetchmany(max_rows + 1)
    truncated = len(rows) > max_rows
    payload = [
        {column: _json_value(value) for column, value in zip(columns, row, strict=False)}
        for row in rows[:max_rows]
    ]
    return columns, payload, truncated


def _configure_sync_readonly(connection, connection_type: str, timeout_sec: int) -> None:
    if connection_type in {"postgres", "mysql", "oracle"}:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        if connection_type == "postgres":
            connection.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_sec * 1000}")
        elif connection_type == "mysql":
            connection.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {timeout_sec * 1000}")
        else:
            raw_connection = connection.connection.driver_connection
            if hasattr(raw_connection, "call_timeout"):
                raw_connection.call_timeout = timeout_sec * 1000
    elif connection_type == "clickhouse":
        connection.exec_driver_sql("SET readonly = 1")
        connection.exec_driver_sql(f"SET max_execution_time = {timeout_sec}")
    else:
        raise AIMCPHTTPError(
            422, "UNSAFE_SQL", "A safe read-only session is unavailable for this connector."
        )


async def _execute_async_engine(
    engine: AsyncEngine,
    sql: str,
    parameters: dict,
    connection_type: str,
    max_rows: int,
    timeout_sec: int,
):
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            if connection_type in {"postgres", "mysql", "oracle", "clickhouse"}:
                command = {
                    "postgres": "SET TRANSACTION READ ONLY",
                    "mysql": "SET TRANSACTION READ ONLY",
                    "oracle": "SET TRANSACTION READ ONLY",
                    "clickhouse": "SET readonly = 1",
                }[connection_type]
                await connection.exec_driver_sql(command)
                if connection_type == "postgres":
                    await connection.exec_driver_sql(
                        f"SET LOCAL statement_timeout = {timeout_sec * 1000}"
                    )
                elif connection_type == "mysql":
                    await connection.exec_driver_sql(
                        f"SET SESSION MAX_EXECUTION_TIME = {timeout_sec * 1000}"
                    )
                elif connection_type == "clickhouse":
                    await connection.exec_driver_sql(f"SET max_execution_time = {timeout_sec}")
                else:
                    raw_connection = connection.sync_connection.connection.driver_connection
                    if hasattr(raw_connection, "call_timeout"):
                        raw_connection.call_timeout = timeout_sec * 1000
            else:
                raise AIMCPHTTPError(
                    422, "UNSAFE_SQL", "A safe read-only session is unavailable for this connector."
                )
            result = await connection.execute(sa.text(sql), parameters)
            return _bounded_result(result, max_rows)
        finally:
            await transaction.rollback()


def _execute_sync_engine(
    engine,
    sql: str,
    parameters: dict,
    connection_type: str,
    max_rows: int,
    timeout_sec: int,
):
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            _configure_sync_readonly(connection, connection_type, timeout_sec)
            return _bounded_result(connection.execute(sa.text(sql), parameters), max_rows)
        finally:
            transaction.rollback()


async def query_database_readonly(
    *,
    principal: MCPPrincipal,
    connection_id: str,
    sql: str,
    parameters: dict[str, Any] | None = None,
    max_rows: int = 100,
) -> dict[str, Any]:
    connection = await get_accessible_connection(principal, connection_id)
    if str(connection.kind).lower() != "sql":
        raise AIMCPHTTPError(422, "CONNECTION_NOT_FOUND_OR_DENIED", "Connection is not SQL.")
    max_rows = max(1, min(max_rows, config.AI_MCP.SQL_MAX_ROWS))
    dialect = str(connection.type).lower()
    if dialect not in {"postgres", "mysql", "oracle", "clickhouse"}:
        raise AIMCPHTTPError(
            422,
            "UNSAFE_SQL",
            "A safe read-only session is unavailable for this connector.",
        )
    parsed_sql, _ = _parse_readonly_sql(sql, dialect)
    resolver = build_resolve_connection_client_use_case(
        engine=async_engine,
        fernet_key=config.SECURITY.FERNET_KEY,
        user_repository_factory=SQLAlchemyUserRepository,
    )
    resolved = await resolver.execute(connection_id=connection_id, actor=principal.user)
    try:
        async with asyncio.timeout(config.AI_MCP.SQL_QUERY_TIMEOUT_SEC):
            if isinstance(resolved.client, AsyncEngine):
                columns, rows, truncated = await _execute_async_engine(
                    resolved.client,
                    parsed_sql,
                    parameters or {},
                    dialect,
                    max_rows,
                    config.AI_MCP.SQL_QUERY_TIMEOUT_SEC,
                )
            else:
                columns, rows, truncated = await asyncio.to_thread(
                    _execute_sync_engine,
                    resolved.client,
                    parsed_sql,
                    parameters or {},
                    dialect,
                    max_rows,
                    config.AI_MCP.SQL_QUERY_TIMEOUT_SEC,
                )
    except TimeoutError as exc:
        raise AIMCPHTTPError(504, "QUERY_TIMEOUT", "SQL query timed out.") from exc
    finally:
        await resolved.aclose()
    result = {"columns": columns, "rows": rows, "truncated": truncated, "max_rows": max_rows}
    size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    if size > config.AI_MCP.SQL_MAX_RESPONSE_BYTES:
        raise AIMCPHTTPError(413, "RESULT_TOO_LARGE", "SQL result exceeds the response size limit.")
    return result


async def _storage(session, principal: MCPPrincipal, connection_id: str):
    dvt_context = await _dvt_service_files_context(
        session=session,
        principal=principal,
        connection_id=connection_id,
    )
    if dvt_context is not None:
        project, node_id, input_name, _ = dvt_context
        yield build_dvt_service_files_storage(
            organization_id=project.organization_id,
            project_id=project.id,
            node_id=node_id,
            input_name=input_name,
        )
        return
    await get_accessible_connection(principal, connection_id)
    async for storage in get_file_storage_facade(connection_id, principal.user):
        yield storage


async def list_storage(
    *,
    session,
    principal: MCPPrincipal,
    connection_id: str,
    path: str = "",
    cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    normalized = StorageRelativePath.from_raw(path)
    offset = decode_cursor(cursor)
    limit = max(1, min(limit, 500))
    async for storage in _storage(session, principal, connection_id):
        tree = await storage.list_nodes(path=str(normalized), max_items=offset + limit + 1)
        nodes = tree.nodes[offset : offset + limit]
        return {
            "backend": tree.backend_kind.value,
            "path": tree.path,
            "items": [
                {
                    "kind": "file" if isinstance(item, StorageFileNode) else "folder",
                    "name": item.name,
                    "path": item.path,
                    **(
                        {
                            "size": item.size,
                            "last_modified": item.last_modified.isoformat()
                            if item.last_modified
                            else None,
                        }
                        if isinstance(item, StorageFileNode)
                        else {}
                    ),
                }
                for item in nodes
            ],
            "next_cursor": encode_cursor(offset + len(nodes), offset + len(tree.nodes))
            if tree.is_truncated or offset + len(nodes) < len(tree.nodes)
            else None,
        }
    raise AIMCPHTTPError(404, "CONNECTION_NOT_FOUND_OR_DENIED", "Storage is unavailable.")


def _preview_bytes(content: bytes, filename: str, max_rows: int) -> dict[str, Any]:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix in {"txt", "log", "md", "yaml", "yml", "xml"}:
        text = content.decode("utf-8", errors="replace")
        return {"format": "text", "text": "\n".join(text.splitlines()[:max_rows])}
    if suffix == "csv":
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        return {
            "format": "csv",
            "rows": [row for _, row in zip(range(max_rows), reader, strict=False)],
        }
    if suffix == "json":
        parsed = json.loads(content.decode("utf-8-sig"))
        if isinstance(parsed, list):
            parsed = parsed[:max_rows]
        return {"format": "json", "value": parsed}
    if suffix == "parquet":
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(io.BytesIO(content))
        batch = next(parquet.iter_batches(batch_size=max_rows), None)
        if batch is None:
            return {
                "format": suffix,
                "columns": list(parquet.schema_arrow.names),
                "rows": [],
            }
        frame = batch.to_pandas()
        return {
            "format": suffix,
            "columns": [str(column) for column in frame.columns],
            "rows": [
                {str(key): _json_value(value) for key, value in row.items()}
                for row in frame.to_dict(orient="records")
            ],
        }
    if suffix in {"xlsx", "xls"}:
        import pandas as pd

        if suffix == "xlsx":
            with zipfile.ZipFile(io.BytesIO(content)) as workbook:
                members = workbook.infolist()
                uncompressed_size = sum(member.file_size for member in members)
                if len(members) > 10_000 or uncompressed_size > 64 * 1024 * 1024:
                    raise AIMCPHTTPError(
                        422,
                        "STORAGE_PREVIEW_UNSUPPORTED",
                        "Spreadsheet expands beyond the safe preview limit.",
                    )
                if any(
                    member.filename.startswith(("/", "\\"))
                    or ".." in member.filename.replace("\\", "/").split("/")
                    for member in members
                ):
                    raise AIMCPHTTPError(
                        422,
                        "STORAGE_PREVIEW_UNSUPPORTED",
                        "Spreadsheet contains unsafe archive paths.",
                    )
        buffer = io.BytesIO(content)
        frame = pd.read_excel(buffer, nrows=max_rows)
        return {
            "format": suffix,
            "columns": [str(column) for column in frame.columns],
            "rows": [
                {str(key): _json_value(value) for key, value in row.items()}
                for row in frame.head(max_rows).to_dict(orient="records")
            ],
        }
    raise AIMCPHTTPError(
        422, "STORAGE_PREVIEW_UNSUPPORTED", "Binary file preview is not supported."
    )


async def preview_storage_file(
    *,
    session,
    principal: MCPPrincipal,
    connection_id: str,
    path: str,
    max_rows: int = 100,
    max_bytes: int = 256 * 1024,
) -> dict[str, Any]:
    normalized = StorageRelativePath.from_raw(path)
    if normalized.is_root:
        raise AIMCPHTTPError(422, "STORAGE_PREVIEW_UNSUPPORTED", "A file path is required.")
    max_rows = max(1, min(max_rows, 100))
    max_bytes = max(1, min(max_bytes, config.AI_MCP.STORAGE_PREVIEW_MAX_BYTES))
    async for storage in _storage(session, principal, connection_id):
        tree = await storage.list_nodes(path=str(normalized.parent), max_items=10000)
        metadata = next(
            (
                item
                for item in tree.nodes
                if isinstance(item, StorageFileNode) and item.path == str(normalized)
            ),
            None,
        )
        if metadata is None:
            raise AIMCPHTTPError(404, "CONNECTION_NOT_FOUND_OR_DENIED", "File was not found.")
        if metadata.size > config.AI_MCP.STORAGE_PREVIEW_MAX_DOWNLOAD_BYTES:
            raise AIMCPHTTPError(
                413,
                "STORAGE_PREVIEW_UNSUPPORTED",
                "File is too large for direct preview; use pipeline nodes instead.",
            )
        downloaded = await storage.download_file(
            path=str(normalized.parent),
            filename=normalized.name,
        )
        if len(downloaded.content) > config.AI_MCP.STORAGE_PREVIEW_MAX_DOWNLOAD_BYTES:
            raise AIMCPHTTPError(
                413,
                "STORAGE_PREVIEW_UNSUPPORTED",
                "File is too large for direct preview; use pipeline nodes instead.",
            )
        preview = await asyncio.to_thread(
            _preview_bytes, downloaded.content, normalized.name, max_rows
        )
        encoded = json.dumps(preview, ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded) > max_bytes:
            raise AIMCPHTTPError(
                413, "RESULT_TOO_LARGE", "File preview exceeds the response size limit."
            )
        return {**preview, "path": str(normalized), "size": metadata.size}
    raise AIMCPHTTPError(404, "CONNECTION_NOT_FOUND_OR_DENIED", "Storage is unavailable.")
