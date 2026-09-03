#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from time import monotonic
from typing import Any


SUPPORTED_SEED_TYPES = {"postgres", "mysql", "clickhouse", "mssql", "oracle"}
SENSITIVE_KEYS = {
    "access_key",
    "access_token_key",
    "api_key",
    "dsn",
    "password",
    "passwd",
    "sasl_plain_password",
    "secret",
    "secrets",
    "session_token",
    "token",
}
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|dsn)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
URL_PASSWORD_PATTERN = re.compile(r"(?P<prefix>://[^:/@\s]+:)[^@/\s]+@")


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


def redact_text(value: str) -> str:
    value = URL_PASSWORD_PATTERN.sub(r"\g<prefix>[REDACTED]@", value)
    return SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1\2[REDACTED]", value)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_KEYS:
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = json_safe(item)
        return result
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump(mode="json"))
    return redact_text(str(value))


def read_json_file(path_value: str) -> Any:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_connection_draft(spec_path: str) -> Any:
    spec = read_json_file(spec_path)
    if not isinstance(spec, dict):
        raise ValueError("Connection spec must be a JSON object")
    if spec.get("secrets"):
        raise ValueError("Raw secrets are forbidden; use secrets_from_env")
    secrets_from_env = spec.get("secrets_from_env") or {}
    if not isinstance(secrets_from_env, dict):
        raise ValueError("secrets_from_env must be an object")
    secrets: dict[str, str] = {}
    for secret_name, env_name in secrets_from_env.items():
        if not isinstance(env_name, str) or not env_name.strip():
            raise ValueError(f"Environment variable name is invalid for secret '{secret_name}'")
        env_value = os.getenv(env_name)
        if env_value is None:
            raise ValueError(f"Required secret environment variable is not set: {env_name}")
        secrets[str(secret_name)] = env_value

    extra = spec.get("extra") or {}
    if not isinstance(extra, dict):
        raise ValueError("extra must be an object")
    if {"user_id", "organization_id"} & set(extra):
        raise ValueError("Connection owner fields are assigned by the service user")

    allowed = {
        "name",
        "kind",
        "type",
        "driver",
        "driver_options",
        "properties",
        "labels",
        "metadata",
        "extra",
        "secrets",
        "secrets_from_env",
    }
    unexpected = set(spec) - allowed
    if unexpected:
        raise ValueError(f"Unsupported connection spec fields: {sorted(unexpected)}")
    for required in ("name", "kind", "type"):
        if not isinstance(spec.get(required), str) or not spec[required].strip():
            raise ValueError(f"Connection spec field '{required}' is required")

    from src.modules.db_connection import ConnectionDraft

    return ConnectionDraft(
        name=spec["name"].strip(),
        kind=spec["kind"].strip(),
        type=spec["type"].strip(),
        driver=spec.get("driver"),
        driver_options=spec.get("driver_options"),
        properties=spec.get("properties") or {},
        secrets=secrets,
        labels=spec.get("labels") or {},
        metadata=spec.get("metadata") or {},
        extra=extra,
    )


async def build_service_and_actor() -> tuple[Any, Any]:
    import config

    from src.crud.admin.user import get_default_service_user
    from src.db import async_engine
    from src.db.session import AsyncSessionLocal
    from src.modules.db_connection import build_connection_service
    from src.modules.user.infra.repositories import SQLAlchemyUserRepository

    async with AsyncSessionLocal() as session:
        actor = await get_default_service_user(session)
    service = build_connection_service(
        engine=async_engine,
        fernet_key=config.SECURITY.FERNET_KEY,
        user_repository_factory=SQLAlchemyUserRepository,
    )
    return service, actor


def serialize_connection(service: Any, record: Any) -> Any:
    return json_safe(service.build_read_view(record))


async def create_connection(args: argparse.Namespace) -> dict[str, Any]:
    from src.modules.db_connection import ConnectionListQuery

    draft = build_connection_draft(args.spec)
    service, actor = await build_service_and_actor()
    query = ConnectionListQuery(name=draft.name, type=str(draft.type))
    existing = [
        item
        for item in await service.list(query, actor=actor)
        if item.name == draft.name and str(item.type) == str(draft.type)
    ]
    if existing:
        if args.if_exists == "error":
            return {
                "success": False,
                "operation": "create",
                "error": "Connection with the same name and type already exists",
                "matches": len(existing),
            }
        if len(existing) != 1:
            return {
                "success": False,
                "operation": "create",
                "error": "Cannot reuse an ambiguous connection match",
                "matches": len(existing),
            }
        return {
            "success": True,
            "operation": "create",
            "action": "reused",
            "connection": serialize_connection(service, existing[0]),
        }

    record = await service.create(draft, actor=actor)
    return {
        "success": True,
        "operation": "create",
        "action": "created",
        "connection": serialize_connection(service, record),
    }


async def check_connection(args: argparse.Namespace) -> dict[str, Any]:
    transient_draft = build_connection_draft(args.spec) if args.spec else None
    service, actor = await build_service_and_actor()
    started_at = monotonic()
    if args.connection_id:
        result = await service.check_stored(args.connection_id, actor=actor)
        target = {"connection_id": args.connection_id}
    else:
        result = await service.check_payload(transient_draft, actor=actor)
        target = {"transient": True}
    return {
        "success": True,
        "operation": "check",
        **target,
        "duration_ms": int((monotonic() - started_at) * 1000),
        "status": json_safe(result),
    }


def validate_identifier(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
        raise ValueError(f"{field_name} must contain only letters, digits and underscores")
    return normalized


def seed_ddl(connection_type: str, table_name: str) -> str:
    if connection_type == "oracle":
        return (
            f"CREATE TABLE {table_name} (id NUMBER PRIMARY KEY, label VARCHAR2(100) NOT NULL, "
            "amount NUMBER(12, 2) NOT NULL, created_at DATE NOT NULL)"
        )
    if connection_type == "mssql":
        return (
            f"CREATE TABLE {table_name} (id INT PRIMARY KEY, label NVARCHAR(100) NOT NULL, "
            "amount DECIMAL(12, 2) NOT NULL, created_at DATE NOT NULL)"
        )
    if connection_type == "clickhouse":
        return (
            f"CREATE TABLE {table_name} (id UInt32, label String, amount Decimal(12, 2), "
            "created_at Date) ENGINE = MergeTree ORDER BY id"
        )
    if connection_type == "mysql":
        return (
            f"CREATE TABLE {table_name} (id INT PRIMARY KEY, label VARCHAR(100) NOT NULL, "
            "amount DECIMAL(12, 2) NOT NULL, created_at DATE NOT NULL)"
        )
    return (
        f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY, label VARCHAR(100) NOT NULL, "
        "amount NUMERIC(12, 2) NOT NULL, created_at DATE NOT NULL)"
    )


def load_seed_rows(path_value: str | None) -> list[dict[str, Any]]:
    rows = read_json_file(path_value) if path_value else [
        {"id": 1, "label": "alpha", "amount": 125.50, "created_at": "2026-04-01"},
        {"id": 2, "label": "beta", "amount": 320.00, "created_at": "2026-04-10"},
        {"id": 3, "label": "gamma", "amount": 875.25, "created_at": "2026-04-15"},
    ]
    if not isinstance(rows, list) or not rows:
        raise ValueError("Seed rows must be a non-empty JSON list")
    normalized: list[dict[str, Any]] = []
    required = {"id", "label", "amount", "created_at"}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"rows[{index}] must be an object")
        missing = required - set(row)
        if missing:
            raise ValueError(f"rows[{index}] is missing columns: {sorted(missing)}")
        normalized.append(
            {
                "id": row["id"],
                "label": row["label"],
                "amount": row["amount"],
                "created_at": (
                    date.fromisoformat(row["created_at"])
                    if isinstance(row["created_at"], str)
                    else row["created_at"]
                ),
            }
        )
    return normalized


async def seed_table(args: argparse.Namespace) -> dict[str, Any]:
    import sqlalchemy as sa
    from sqlalchemy.engine import Engine

    if args.if_exists in {"truncate", "drop"} and not args.allow_destructive:
        return {
            "success": False,
            "operation": "seed",
            "error": "truncate/drop requires --allow-destructive",
        }
    table_name = validate_identifier(args.table, field_name="table")
    rows = load_seed_rows(args.rows)
    service, actor = await build_service_and_actor()
    record = await service.get(args.connection_id, actor=actor)
    connection_type = str(record.type)
    if connection_type not in SUPPORTED_SEED_TYPES:
        return {
            "success": False,
            "operation": "seed",
            "error": f"Unsupported seed connection type: {connection_type}",
            "supported_types": sorted(SUPPORTED_SEED_TYPES),
        }
    engine = await service.get_client(record)
    if not isinstance(engine, Engine):
        return {
            "success": False,
            "operation": "seed",
            "error": f"Connection returned unsupported client type: {type(engine).__name__}",
        }

    ddl = seed_ddl(connection_type, table_name)
    insert = sa.text(
        f"INSERT INTO {table_name} (id, label, amount, created_at) "
        "VALUES (:id, :label, :amount, :created_at)"
    )
    table_exists = sa.inspect(engine).has_table(table_name)
    action = "created"
    with engine.begin() as connection:
        if table_exists:
            if args.if_exists == "fail":
                return {
                    "success": False,
                    "operation": "seed",
                    "error": f"Table already exists: {table_name}",
                    "table_name": table_name,
                }
            if args.if_exists == "drop":
                connection.execute(sa.text(f"DROP TABLE {table_name}"))
                connection.execute(sa.text(ddl))
                action = "dropped_created"
            else:
                connection.execute(sa.text(f"TRUNCATE TABLE {table_name}"))
                action = "truncated"
        else:
            connection.execute(sa.text(ddl))
        connection.execute(insert, rows)
        selected = connection.execute(
            sa.text(f"SELECT id, label, amount, created_at FROM {table_name} ORDER BY id")
        ).mappings().all()

    return {
        "success": True,
        "operation": "seed",
        "connection_id": args.connection_id,
        "connection_type": connection_type,
        "table_name": table_name,
        "action": action,
        "inserted_rows": len(rows),
        "rows": [json_safe(dict(item)) for item in selected],
    }


async def run_worker(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = find_repo_root()
    load_project_env(repo_root)
    sys.path.insert(0, str(repo_root))
    if args.operation == "create":
        return await create_connection(args)
    if args.operation == "check":
        return await check_connection(args)
    return await seed_table(args)


def run_bounded_worker(args: argparse.Namespace) -> dict[str, Any]:
    command = [sys.executable, str(Path(__file__).resolve()), "--_worker", *sys.argv[1:]]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=args.timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "operation": args.operation,
            "timed_out": True,
            "error": f"Operation timed out after {args.timeout_sec} seconds",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "success": False,
            "operation": args.operation,
            "error": "Worker did not return valid JSON",
            "stderr": redact_text(completed.stderr.strip()),
        }
    if completed.stderr.strip():
        payload.setdefault("diagnostics", redact_text(completed.stderr.strip()))
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare DVT DB connection test fixtures")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--spec", required=True)
    create.add_argument("--if-exists", choices=("error", "reuse"), default="error")
    create.add_argument("--timeout-sec", type=int, default=30)

    check = subparsers.add_parser("check")
    target = check.add_mutually_exclusive_group(required=True)
    target.add_argument("--connection-id")
    target.add_argument("--spec")
    check.add_argument("--timeout-sec", type=int, default=15)

    seed = subparsers.add_parser("seed")
    seed.add_argument("--connection-id", required=True)
    seed.add_argument("--table", default="dvt_sample_data")
    seed.add_argument("--rows")
    seed.add_argument("--if-exists", choices=("fail", "truncate", "drop"), default="fail")
    seed.add_argument("--allow-destructive", action="store_true")
    seed.add_argument("--timeout-sec", type=int, default=30)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.timeout_sec < 1:
            raise ValueError("timeout_sec must be >= 1")
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        payload = asyncio.run(run_worker(args)) if args._worker else run_bounded_worker(args)
    except Exception as exc:  # noqa: BLE001
        payload = {
            "success": False,
            "operation": getattr(args, "operation", None),
            "error": f"{type(exc).__name__}: {redact_text(str(exc))}",
        }
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
