"""Документ lineage проекции: домен ↔ JSON. Чужая версия формата читается как отсутствие lineage."""

from __future__ import annotations

from typing import Any

from ..domain import (
    LINEAGE_SCHEMA_VERSION,
    ColumnLineage,
    DiagnosticReason,
    InvalidLineageRefError,
    LineageOp,
    LineageRef,
    PortLineage,
    PortStatus,
    ProjectLineage,
)


def lineage_to_json(lineage: ProjectLineage) -> dict[str, Any]:
    return {
        "version": lineage.version,
        "truncated": lineage.truncated,
        "ports": [
            {
                "node_id": port.node_id,
                "node_name": port.node_name,
                "port": port.port,
                "role": port.role,
                "status": port.status.value,
                "reason": port.reason.value if port.reason else None,
                "detail": port.detail,
                "columns": [
                    {
                        "name": column.name,
                        "op": column.op.value,
                        "deps": [dep.key for dep in column.deps],
                        "deps_unknown": column.deps_unknown,
                        "origin": column.origin.key if column.origin else None,
                        "details": dict(column.details),
                    }
                    for column in port.columns
                ],
            }
            for port in lineage.ports
        ],
    }


def lineage_from_json(payload: Any) -> ProjectLineage | None:
    if not isinstance(payload, dict) or payload.get("version") != LINEAGE_SCHEMA_VERSION:
        return None
    ports: list[PortLineage] = []
    for raw_port in payload.get("ports") or []:
        if not isinstance(raw_port, dict):
            continue
        try:
            status = PortStatus(str(raw_port.get("status")))
        except ValueError:
            continue
        reason = _reason(raw_port.get("reason"))
        columns: list[ColumnLineage] = []
        for raw_column in raw_port.get("columns") or []:
            column = _column_from_json(raw_column)
            if column is not None:
                columns.append(column)
        ports.append(
            PortLineage(
                node_id=str(raw_port.get("node_id")),
                node_name=str(raw_port.get("node_name") or ""),
                port=str(raw_port.get("port")),
                role=str(raw_port.get("role") or "output"),
                status=status,
                reason=reason,
                detail=raw_port.get("detail"),
                columns=tuple(columns),
            )
        )
    return ProjectLineage(ports=tuple(ports), version=LINEAGE_SCHEMA_VERSION, truncated=bool(payload.get("truncated")))


def _column_from_json(raw: Any) -> ColumnLineage | None:
    if not isinstance(raw, dict) or not raw.get("name"):
        return None
    try:
        op = LineageOp(str(raw.get("op")))
        deps = tuple(LineageRef.parse(str(key)) for key in raw.get("deps") or [])
        origin_key = raw.get("origin")
        origin = LineageRef.parse(str(origin_key)) if origin_key else None
    except (ValueError, InvalidLineageRefError):
        return None
    details = raw.get("details")
    return ColumnLineage(
        name=str(raw["name"]),
        op=op,
        deps=deps,
        deps_unknown=bool(raw.get("deps_unknown")),
        details=dict(details) if isinstance(details, dict) else {},
        origin=origin,
    )


def _reason(value: Any) -> DiagnosticReason | None:
    if not value:
        return None
    try:
        return DiagnosticReason(str(value))
    except ValueError:
        return None
