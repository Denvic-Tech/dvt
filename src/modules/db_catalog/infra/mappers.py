from __future__ import annotations

import json
from datetime import datetime

from ..domain.entities import (
    CatalogCacheEntry,
    CatalogColumn,
    CatalogDatabase,
    CatalogResult,
    CatalogSchema,
    CatalogTableDetails,
    CatalogTableSummary,
)
from ..domain.types import CatalogTableKind


def dump_cache_entry(entry: CatalogCacheEntry) -> bytes:
    payload = {
        "version": 1,
        "catalog_version": entry.catalog_version,
        "loaded_at": entry.loaded_at.isoformat(),
        "expires_at": entry.expires_at.isoformat(),
        "result": {
            "items": [_dump_item(item) for item in entry.result.items],
            "next_cursor": entry.result.next_cursor,
            "table": _dump_table(entry.result.table) if entry.result.table else None,
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def load_cache_entry(payload: bytes) -> CatalogCacheEntry:
    raw = json.loads(payload)
    if raw.get("version") != 1:
        raise ValueError("Unsupported catalog cache version.")
    result = raw["result"]
    return CatalogCacheEntry(
        result=CatalogResult(
            items=tuple(_load_item(item) for item in result.get("items", [])),
            next_cursor=result.get("next_cursor"),
            table=_load_table(result["table"]) if result.get("table") else None,
        ),
        catalog_version=raw["catalog_version"],
        loaded_at=datetime.fromisoformat(raw["loaded_at"]),
        expires_at=datetime.fromisoformat(raw["expires_at"]),
    )


def _dump_item(item) -> dict:
    if isinstance(item, CatalogDatabase):
        return {"type": "database", "name": item.name, "is_current": item.is_current}
    if isinstance(item, CatalogSchema):
        return {"type": "schema", "name": item.name, "database_name": item.database_name}
    if isinstance(item, CatalogTableSummary):
        return {
            "type": "table",
            "name": item.name,
            "kind": item.kind.value,
            "database_name": item.database_name,
            "schema_name": item.schema_name,
        }
    raise TypeError(f"Unsupported catalog item: {type(item)!r}")


def _load_item(raw: dict):
    item_type = raw["type"]
    if item_type == "database":
        return CatalogDatabase(name=raw["name"], is_current=raw.get("is_current", False))
    if item_type == "schema":
        return CatalogSchema(name=raw["name"], database_name=raw.get("database_name"))
    if item_type == "table":
        return CatalogTableSummary(
            name=raw["name"],
            kind=CatalogTableKind(raw["kind"]),
            database_name=raw.get("database_name"),
            schema_name=raw.get("schema_name"),
        )
    raise ValueError(f"Unsupported catalog item type: {item_type!r}")


def _dump_table(table: CatalogTableDetails) -> dict:
    return {
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
    }


def _load_table(raw: dict) -> CatalogTableDetails:
    return CatalogTableDetails(
        name=raw["name"],
        kind=CatalogTableKind(raw["kind"]),
        database_name=raw.get("database_name"),
        schema_name=raw.get("schema_name"),
        columns=tuple(CatalogColumn(**column) for column in raw.get("columns", [])),
    )
