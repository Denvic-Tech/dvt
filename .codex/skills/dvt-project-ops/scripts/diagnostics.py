#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any


VALID_OPERATORS = {">", "<", ">=", "<=", "=="}
OPERATOR_ALIASES = {"=>": ">=", "=<": "<="}
TOKEN_PATTERN = re.compile(r"dvt_mcp_[A-Za-z0-9-]+\.[A-Za-z0-9_-]+")
BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*")
URL_PASSWORD_PATTERN = re.compile(r"(?P<prefix>://[^:/@\s]+:)[^@/\s]+@")
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|dsn)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
AWS_ACCESS_KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
TOPOSORT_TARGET_RE = re.compile(r"^Performing topological sort\. Target nodes: (?P<value>.+)$")
TOPOSORT_ORDER_RE = re.compile(r"^Topological sort successful\. Order: (?P<value>\[.*\])$")
PROCESSING_NODE_RE = re.compile(r"^Processing node (?P<node_id>\S+) \((?P<node_name>[^)]+)\)\.$")


def find_repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".git").exists() and (candidate / "src").is_dir():
            return candidate
    raise RuntimeError("Visual_transformer repository root was not found")


def load_project_env(repo_root: Path) -> None:
    env_path = repo_root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def redact(value: str | None) -> str | None:
    if value is None:
        return None
    value = TOKEN_PATTERN.sub("[REDACTED_MCP_TOKEN]", value)
    value = BEARER_PATTERN.sub(r"\1[REDACTED]", value)
    value = URL_PASSWORD_PATTERN.sub(r"\g<prefix>[REDACTED]@", value)
    value = SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1\2[REDACTED]", value)
    return AWS_ACCESS_KEY_PATTERN.sub("[REDACTED_ACCESS_KEY]", value)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump())
    return str(value)


def parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def normalize_operator(value: str) -> str:
    normalized = OPERATOR_ALIASES.get(value, value)
    if normalized not in VALID_OPERATORS:
        raise ValueError(f"Unsupported datetime operator: {value}")
    return normalized


def add_datetime_filter(filters: list[Any], column: Any, value: datetime | None, operator: str) -> None:
    if value is None:
        return
    operations = {
        ">": column > value,
        "<": column < value,
        ">=": column >= value,
        "<=": column <= value,
        "==": column == value,
    }
    filters.append(operations[operator])


def validate_pagination(limit: int, offset: int) -> None:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    if offset < 0:
        raise ValueError("offset must be >= 0")


def contains(column: Any, value: str) -> Any:
    import sqlalchemy as sa

    return sa.func.lower(column).like(f"%{value.lower()}%")


def serialize_log(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": json_safe(row["created_at"]),
        "level": row["level"],
        "service_name": row["service_name"],
        "message": redact(row["message"]),
        "exception_traceback": redact(row["exception_traceback"]),
        "user_id": row["user_id"],
        "task_id": row["task_id"],
        "project_id": row.get("project_id"),
        "logger_name": row["logger_name"],
        "module": row["module"],
        "function": row["function"],
        "line": row["line"],
    }


def query_logs(args: argparse.Namespace) -> dict[str, Any]:
    import sqlalchemy as sa

    from src.db import engine

    validate_pagination(args.limit, args.offset)
    operator = normalize_operator(args.created_at_op)
    created_at = parse_datetime(args.created_at)
    metadata = sa.MetaData()
    logs_table = sa.Table("logs", metadata, autoload_with=engine)
    tasks_table = sa.Table("tasks", metadata, autoload_with=engine)
    join_from = logs_table.outerjoin(tasks_table, logs_table.c.task_id == tasks_table.c.task_id)
    filters: list[Any] = []
    add_datetime_filter(filters, logs_table.c.created_at, created_at, operator)
    if args.level:
        filters.append(logs_table.c.level == args.level)
    if args.service_name:
        filters.append(logs_table.c.service_name == args.service_name)
    if args.message:
        filters.append(contains(logs_table.c.message, args.message))
    if args.exception_traceback:
        filters.append(contains(logs_table.c.exception_traceback, args.exception_traceback))
    if args.user_id:
        filters.append(logs_table.c.user_id == args.user_id)
    if args.task_id:
        filters.append(logs_table.c.task_id == args.task_id)
    if args.project_id:
        filters.append(tasks_table.c.project_id == args.project_id)
    if args.module:
        filters.append(logs_table.c.module == args.module)
    if args.function:
        filters.append(logs_table.c.function == args.function)
    if args.line is not None:
        filters.append(logs_table.c.line == args.line)

    direction = sa.desc if args.sort == "desc" else sa.asc
    query = (
        sa.select(
            logs_table.c.id,
            logs_table.c.created_at,
            logs_table.c.level,
            logs_table.c.service_name,
            logs_table.c.message,
            logs_table.c.exception_traceback,
            logs_table.c.user_id,
            logs_table.c.task_id,
            tasks_table.c.project_id.label("project_id"),
            logs_table.c.logger_name,
            logs_table.c.module,
            logs_table.c.function,
            logs_table.c.line,
        )
        .select_from(join_from)
        .where(*filters)
        .order_by(direction(logs_table.c.created_at), direction(logs_table.c.id))
        .limit(args.limit)
        .offset(args.offset)
    )
    count_query = sa.select(sa.func.count()).select_from(join_from).where(*filters)
    with engine.connect() as connection:
        total = int(connection.execute(count_query).scalar_one())
        rows = connection.execute(query).mappings().all()
    items = [serialize_log(row) for row in rows]
    return {
        "success": True,
        "operation": "logs",
        "total": total,
        "count": len(items),
        "limit": args.limit,
        "offset": args.offset,
        "items": items,
    }


def task_filters(args: argparse.Namespace, task_record: Any) -> list[Any]:
    filters: list[Any] = []
    for argument_name, column_name in (
        ("task_id", "task_id"),
        ("user_id", "user_id"),
        ("project_id", "project_id"),
        ("assigned_worker_id", "assigned_worker_id"),
        ("mode", "mode"),
        ("source", "source"),
    ):
        value = getattr(args, argument_name, None)
        if value:
            filters.append(getattr(task_record, column_name) == value)
    if getattr(args, "status", None):
        filters.append(task_record.status.in_([item.upper() for item in args.status]))
    if getattr(args, "message", None):
        filters.append(contains(task_record.message, args.message))
    if getattr(args, "force_exec", None) is not None:
        filters.append(task_record.force_exec == args.force_exec)
    add_datetime_filter(
        filters,
        task_record.queued_at,
        parse_datetime(getattr(args, "queued_at", None)),
        normalize_operator(getattr(args, "queued_at_op", ">=")),
    )
    add_datetime_filter(
        filters,
        task_record.updated_at,
        parse_datetime(getattr(args, "updated_at", None)),
        normalize_operator(getattr(args, "updated_at_op", ">=")),
    )
    return filters


def serialize_task(row: Any) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "user_id": row["user_id"],
        "organization_id": row["organization_id"],
        "project_id": row["project_id"],
        "project_name": row["project_name"],
        "mode": json_safe(row["mode"]),
        "force_exec": row["force_exec"],
        "source": json_safe(row["source"]),
        "status": json_safe(row["status"]),
        "message": redact(row["message"]),
        "termination_reason": row["termination_reason"],
        "assigned_worker_id": row["assigned_worker_id"],
        "schedule_run_id": row["schedule_run_id"],
        "schedule_attempt": row["schedule_attempt"],
        "queued_at": json_safe(row["queued_at"]),
        "started_at": json_safe(row["started_at"]),
        "finished_at": json_safe(row["finished_at"]),
        "updated_at": json_safe(row["updated_at"]),
    }


def query_tasks(args: argparse.Namespace) -> dict[str, Any]:
    import sqlalchemy as sa

    from src.db import engine

    validate_pagination(args.limit, args.offset)
    metadata = sa.MetaData()
    tasks_table = sa.Table("tasks", metadata, autoload_with=engine)
    projects_table = sa.Table("projects", metadata, autoload_with=engine)
    filters = task_filters(args, tasks_table.c)
    sort_column = getattr(tasks_table.c, args.sort_by)
    direction = sa.desc if args.sort == "desc" else sa.asc
    query = (
        sa.select(
            tasks_table.c.task_id,
            tasks_table.c.user_id,
            tasks_table.c.organization_id,
            tasks_table.c.project_id,
            projects_table.c.name.label("project_name"),
            tasks_table.c.mode,
            tasks_table.c.force_exec,
            tasks_table.c.source,
            tasks_table.c.status,
            tasks_table.c.message,
            tasks_table.c.termination_reason,
            tasks_table.c.assigned_worker_id,
            tasks_table.c.schedule_run_id,
            tasks_table.c.schedule_attempt,
            tasks_table.c.queued_at,
            tasks_table.c.started_at,
            tasks_table.c.finished_at,
            tasks_table.c.updated_at,
        )
        .select_from(tasks_table.outerjoin(
            projects_table, tasks_table.c.project_id == projects_table.c.id
        ))
        .where(*filters)
        .order_by(direction(sort_column), direction(tasks_table.c.task_id))
        .limit(args.limit)
        .offset(args.offset)
    )
    count_query = sa.select(sa.func.count()).select_from(tasks_table).where(*filters)
    with engine.connect() as connection:
        total = int(connection.execute(count_query).scalar_one())
        rows = connection.execute(query).mappings().all()

    items = [serialize_task(item) for item in rows]
    return {
        "success": True,
        "operation": "tasks",
        "total": total,
        "count": len(items),
        "limit": args.limit,
        "offset": args.offset,
        "items": items,
    }


def parse_python_list(raw: str) -> list[str] | None:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return None
    return [str(item) for item in value] if isinstance(value, list) else None


def collect_execution_insights(messages: list[str]) -> dict[str, Any]:
    insights: dict[str, Any] = {
        "target_nodes": None,
        "execution_order": None,
        "processed_nodes": [],
        "contains_service_output_terminal": False,
        "contains_write_node": False,
    }
    for message in messages:
        target_match = TOPOSORT_TARGET_RE.match(message)
        if target_match:
            raw = target_match.group("value").strip()
            if raw in {"None", "null"}:
                insights["target_nodes"] = None
            elif raw.startswith("["):
                insights["target_nodes"] = parse_python_list(raw)
            else:
                insights["target_nodes"] = [raw]
            continue
        order_match = TOPOSORT_ORDER_RE.match(message)
        if order_match:
            order = parse_python_list(order_match.group("value").strip())
            insights["execution_order"] = order
            insights["contains_service_output_terminal"] = bool(
                order and any(item.startswith("__service_output") for item in order)
            )
            continue
        node_match = PROCESSING_NODE_RE.match(message)
        if node_match:
            node_name = node_match.group("node_name")
            processed = {"node_id": node_match.group("node_id"), "node_name": node_name}
            if processed not in insights["processed_nodes"]:
                insights["processed_nodes"].append(processed)
            if node_name.startswith("WriteDataFrameToDB"):
                insights["contains_write_node"] = True
    return insights


def inspect_task(args: argparse.Namespace) -> dict[str, Any]:
    import sqlalchemy as sa

    from src.db import engine

    metadata = sa.MetaData()
    tasks_table = sa.Table("tasks", metadata, autoload_with=engine)
    projects_table = sa.Table("projects", metadata, autoload_with=engine)
    logs_table = sa.Table("logs", metadata, autoload_with=engine)

    task_query = (
        sa.select(
            tasks_table.c.task_id,
            tasks_table.c.user_id,
            tasks_table.c.organization_id,
            tasks_table.c.project_id,
            projects_table.c.name.label("project_name"),
            tasks_table.c.mode,
            tasks_table.c.force_exec,
            tasks_table.c.source,
            tasks_table.c.status,
            tasks_table.c.message,
            tasks_table.c.termination_reason,
            tasks_table.c.assigned_worker_id,
            tasks_table.c.schedule_run_id,
            tasks_table.c.schedule_attempt,
            tasks_table.c.queued_at,
            tasks_table.c.started_at,
            tasks_table.c.finished_at,
            tasks_table.c.updated_at,
        )
        .select_from(tasks_table.outerjoin(
            projects_table, tasks_table.c.project_id == projects_table.c.id
        ))
        .where(tasks_table.c.task_id == args.task_id)
        .limit(1)
    )
    logs_query = (
        sa.select(logs_table.c.message)
        .where(logs_table.c.task_id == args.task_id)
        .order_by(logs_table.c.created_at.asc(), logs_table.c.id.asc())
    )
    with engine.connect() as connection:
        row = connection.execute(task_query).mappings().first()
        if row is None:
            return {
                "success": False,
                "operation": "task",
                "task_id": args.task_id,
                "error": "Task not found",
            }
        messages = list(connection.execute(logs_query).scalars().all())

    task = serialize_task(row)
    task["execution_insights"] = collect_execution_insights(messages)
    task["log_count"] = len(messages)
    return {"success": True, "operation": "task", "item": task}


def add_common_time_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--queued-at")
    parser.add_argument("--queued-at-op", default=">=")
    parser.add_argument("--updated-at")
    parser.add_argument("--updated-at-op", default=">=")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query DVT internal logs and task state")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    logs = subparsers.add_parser("logs")
    logs.add_argument("--created-at")
    logs.add_argument("--created-at-op", default=">=")
    logs.add_argument("--level")
    logs.add_argument("--service-name")
    logs.add_argument("--message")
    logs.add_argument("--exception-traceback")
    logs.add_argument("--user-id")
    logs.add_argument("--task-id")
    logs.add_argument("--project-id")
    logs.add_argument("--module")
    logs.add_argument("--function")
    logs.add_argument("--line", type=int)
    logs.add_argument("--sort", choices=("asc", "desc"), default="desc")
    logs.add_argument("--limit", type=int, default=200)
    logs.add_argument("--offset", type=int, default=0)

    tasks = subparsers.add_parser("tasks")
    tasks.add_argument("--task-id")
    tasks.add_argument("--user-id")
    tasks.add_argument("--project-id")
    tasks.add_argument("--status", action="append")
    tasks.add_argument("--mode")
    tasks.add_argument("--source")
    tasks.add_argument("--force-exec", action=argparse.BooleanOptionalAction, default=None)
    tasks.add_argument("--assigned-worker-id")
    tasks.add_argument("--message")
    add_common_time_filters(tasks)
    tasks.add_argument(
        "--sort-by",
        choices=("queued_at", "updated_at", "started_at", "finished_at", "task_id"),
        default="queued_at",
    )
    tasks.add_argument("--sort", choices=("asc", "desc"), default="desc")
    tasks.add_argument("--limit", type=int, default=200)
    tasks.add_argument("--offset", type=int, default=0)

    task = subparsers.add_parser("task")
    task.add_argument("task_id")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        repo_root = find_repo_root()
        load_project_env(repo_root)
        sys.path.insert(0, str(repo_root))
        if args.operation == "logs":
            payload = query_logs(args)
        elif args.operation == "tasks":
            payload = query_tasks(args)
        else:
            payload = inspect_task(args)
    except Exception as exc:  # noqa: BLE001
        payload = {
            "success": False,
            "operation": getattr(args, "operation", None),
            "error": f"{type(exc).__name__}: {redact(str(exc))}",
        }
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
