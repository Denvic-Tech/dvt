#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SERVICE_MAPPING = {
    "gateway": "gateway",
    "task_worker": "task-worker",
    "project_scheduler": "project-scheduler",
    "orchestrator": "orchestrator",
}
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|dsn)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
URL_PASSWORD_PATTERN = re.compile(r"(?P<prefix>://[^:/@\s]+:)[^@/\s]+@")


def redact_text(value: str) -> str:
    value = URL_PASSWORD_PATTERN.sub(r"\g<prefix>[REDACTED]@", value)
    return SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1\2[REDACTED]", value)


def find_repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".git").exists() and (candidate / "docker").is_dir():
            return candidate
    raise RuntimeError("Visual_transformer repository root was not found")


def normalize_service_name(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized not in SERVICE_MAPPING:
        allowed = ", ".join(sorted(SERVICE_MAPPING))
        raise ValueError(f"Unsupported service '{value}'. Allowed: {allowed}")
    return normalized


def compose_prefix(repo_root: Path, stack: str) -> list[str]:
    command = ["docker", "compose", "--project-directory", str(repo_root)]
    if stack == "dev":
        command.extend(
            [
                "-f",
                str(repo_root / "docker" / "docker-compose.base.yaml"),
                "-f",
                str(repo_root / "docker" / "docker-compose.dev.yaml"),
            ]
        )
    elif stack == "production":
        command.extend(["-f", str(repo_root / "docker-compose.yaml")])
    else:
        raise ValueError(f"Unsupported stack: {stack}")
    return command


def run_command(command: list[str], *, repo_root: Path, timeout_sec: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "error": f"Command timed out after {timeout_sec} seconds",
            "command": command,
        }
    except OSError as exc:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"Unable to run command: {type(exc).__name__}: {exc}",
            "command": command,
        }

    return {
        "success": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "error": None if completed.returncode == 0 else "Command failed",
        "command": command,
    }


def parse_compose_ps(stdout: str) -> list[dict[str, Any]]:
    text = stdout.strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        rows: list[dict[str, Any]] = []
        for raw_line in text.splitlines():
            try:
                item = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return [parsed] if isinstance(parsed, dict) else []


def effective_status(state: str | None, status: str | None, health: str | None) -> str:
    tokens = [str(item or "").strip().lower() for item in (state, status, health)]
    if any("unhealthy" in token or "failed" in token or "error" in token for token in tokens):
        return "unhealthy"
    if any("restart" in token for token in tokens):
        return "restarting"
    if any(token in {"running", "up", "healthy"} or token.startswith("up ") for token in tokens):
        return "running"
    if any(token in {"stopped", "exited", "created", "paused", "dead"} for token in tokens):
        return "stopped"
    return "unknown"


def collect_services(
    repo_root: Path,
    *,
    stack: str,
    requested_services: list[str] | None,
    verbose: bool,
) -> dict[str, Any]:
    requested = (
        [normalize_service_name(item) for item in requested_services]
        if requested_services
        else list(SERVICE_MAPPING)
    )
    command = [*compose_prefix(repo_root, stack), "ps", "--all", "--format", "json"]
    result = run_command(command, repo_root=repo_root, timeout_sec=15)
    if not result["success"]:
        return {
            "success": False,
            "operation": "status",
            "stack": stack,
            "interpreter": {
                "executable": sys.executable,
                "version": ".".join(str(part) for part in sys.version_info[:3]),
            },
            "error": result["error"],
            "stderr": redact_text(result["stderr"].strip()),
            "command": command,
            "services": [],
        }

    rows = parse_compose_ps(result["stdout"])
    by_service = {str(row.get("Service") or ""): row for row in rows if row.get("Service")}
    services: list[dict[str, Any]] = []
    for logical_name in requested:
        compose_name = SERVICE_MAPPING[logical_name]
        row = by_service.get(compose_name)
        state = str(row.get("State") or "") if row else ""
        status = str(row.get("Status") or "") if row else ""
        health = str(row.get("Health") or "") if row else ""
        item: dict[str, Any] = {
            "service_name": logical_name,
            "compose_service": compose_name,
            "effective_status": effective_status(state, status, health),
            "state": state or None,
            "status": status or None,
            "health": health or None,
            "container_name": row.get("Name") if row else None,
            "container_id": row.get("ID") if row else None,
        }
        if verbose:
            item["raw"] = row
        services.append(item)

    return {
        "success": True,
        "operation": "status",
        "stack": stack,
        "interpreter": {
            "executable": sys.executable,
            "version": ".".join(str(part) for part in sys.version_info[:3]),
        },
        "services": services,
    }


def restart_service(
    repo_root: Path,
    *,
    stack: str,
    service_name: str,
    timeout_sec: int,
) -> dict[str, Any]:
    logical_name = normalize_service_name(service_name)
    compose_name = SERVICE_MAPPING[logical_name]
    before = collect_services(
        repo_root,
        stack=stack,
        requested_services=[logical_name],
        verbose=False,
    )
    command = [*compose_prefix(repo_root, stack), "restart", compose_name]
    restart = run_command(command, repo_root=repo_root, timeout_sec=timeout_sec)
    after = collect_services(
        repo_root,
        stack=stack,
        requested_services=[logical_name],
        verbose=False,
    )
    after_item = (after.get("services") or [{}])[0]
    post_status = after_item.get("effective_status", "unknown")
    success = bool(restart["success"] and after.get("success") and post_status == "running")
    error = None
    if not restart["success"]:
        error = restart["error"] or "Docker Compose restart failed"
    elif not after.get("success"):
        error = "Service restart completed but post-restart inspection failed"
    elif post_status != "running":
        error = f"Service is not running after restart: {post_status}"

    return {
        "success": success,
        "operation": "restart",
        "stack": stack,
        "service_name": logical_name,
        "compose_service": compose_name,
        "error": error,
        "before": (before.get("services") or [None])[0],
        "after": after_item if after.get("success") else None,
        "attempt": {
            "exit_code": restart["exit_code"],
            "stderr": redact_text(restart["stderr"].strip()),
            "command": command,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or restart DVT Docker services")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    status = subparsers.add_parser("status", help="Inspect service status")
    status.add_argument("--service", action="append", dest="services")
    status.add_argument("--stack", choices=("dev", "production"), default="dev")
    status.add_argument("--verbose", action="store_true")

    restart = subparsers.add_parser("restart", help="Restart one Docker service")
    restart.add_argument("service_name")
    restart.add_argument("--stack", choices=("dev", "production"), default="dev")
    restart.add_argument("--timeout-sec", type=int, default=120)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        repo_root = find_repo_root()
        if args.operation == "status":
            payload = collect_services(
                repo_root,
                stack=args.stack,
                requested_services=args.services,
                verbose=args.verbose,
            )
        else:
            if args.timeout_sec < 1:
                raise ValueError("timeout_sec must be >= 1")
            payload = restart_service(
                repo_root,
                stack=args.stack,
                service_name=args.service_name,
                timeout_sec=args.timeout_sec,
            )
    except Exception as exc:  # noqa: BLE001
        payload = {"success": False, "error": f"{type(exc).__name__}: {exc}"}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
