from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
SCRIPTS_ROOT = REPO_ROOT / ".codex" / "skills" / "dvt-project-ops" / "scripts"


def load_script(name: str):
    module_name = f"test_dvt_project_ops_{name}"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS_ROOT / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_compose_prefix_uses_project_dev_stack() -> None:
    runtime = load_script("runtime_services")

    command = runtime.compose_prefix(REPO_ROOT, "dev")

    assert command == [
        "docker",
        "compose",
        "--project-directory",
        str(REPO_ROOT),
        "-f",
        str(REPO_ROOT / "docker" / "docker-compose.base.yaml"),
        "-f",
        str(REPO_ROOT / "docker" / "docker-compose.dev.yaml"),
    ]


def test_runtime_parses_json_lines_and_prioritizes_unhealthy() -> None:
    runtime = load_script("runtime_services")
    stdout = '\n'.join([
        json.dumps({"Service": "gateway", "State": "running", "Health": "healthy"}),
        json.dumps({"Service": "orchestrator", "State": "running", "Health": "unhealthy"}),
    ])

    rows = runtime.parse_compose_ps(stdout)

    assert len(rows) == 2
    assert runtime.effective_status("running", "Up", "unhealthy") == "unhealthy"
    assert runtime.redact_text("password=secret-value") == "password=[REDACTED]"


def test_runtime_restart_fails_when_post_status_is_not_running(monkeypatch) -> None:
    runtime = load_script("runtime_services")
    snapshots = [
        {"success": True, "services": [{"effective_status": "running"}]},
        {"success": True, "services": [{"effective_status": "unhealthy"}]},
    ]
    monkeypatch.setattr(runtime, "collect_services", lambda *args, **kwargs: snapshots.pop(0))
    monkeypatch.setattr(
        runtime,
        "run_command",
        lambda *args, **kwargs: {
            "success": True,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "error": None,
        },
    )

    result = runtime.restart_service(
        REPO_ROOT,
        stack="dev",
        service_name="gateway",
        timeout_sec=30,
    )

    assert result["success"] is False
    assert result["after"]["effective_status"] == "unhealthy"


def test_diagnostics_redacts_secrets_and_collects_current_insights() -> None:
    diagnostics = load_script("diagnostics")
    messages = [
        "Performing topological sort. Target nodes: ['sink']",
        "Topological sort successful. Order: ['source', '__service_output_sink__']",
        "Processing node sink (WriteDataFrameToDBV4).",
        "Processing node sink (WriteDataFrameToDBV4).",
    ]

    insights = diagnostics.collect_execution_insights(messages)

    assert insights["target_nodes"] == ["sink"]
    assert insights["contains_service_output_terminal"] is True
    assert insights["contains_write_node"] is True
    assert insights["processed_nodes"] == [
        {"node_id": "sink", "node_name": "WriteDataFrameToDBV4"}
    ]
    assert diagnostics.redact("password=secret-value") == "password=[REDACTED]"


def test_db_spec_loads_secrets_from_environment_only(tmp_path, monkeypatch) -> None:
    fixtures = load_script("db_fixtures")
    spec_path = tmp_path / "connection.json"
    spec_path.write_text(
        json.dumps(
            {
                "name": "test-postgres",
                "kind": "sql",
                "type": "postgres",
                "properties": {"host": "localhost"},
                "secrets_from_env": {"password": "TEST_DVT_DB_PASSWORD"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_DVT_DB_PASSWORD", "not-printed")

    draft = fixtures.build_connection_draft(str(spec_path))

    assert draft.secrets == {"password": "not-printed"}
    assert fixtures.json_safe({"secrets": draft.secrets}) == {"secrets": "[REDACTED]"}


def test_db_spec_rejects_raw_secrets(tmp_path) -> None:
    fixtures = load_script("db_fixtures")
    spec_path = tmp_path / "connection.json"
    spec_path.write_text(
        json.dumps(
            {
                "name": "unsafe",
                "kind": "sql",
                "type": "postgres",
                "secrets": {"password": "raw"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Raw secrets are forbidden"):
        fixtures.build_connection_draft(str(spec_path))


def test_db_seed_requires_explicit_destructive_flag() -> None:
    fixtures = load_script("db_fixtures")
    args = argparse.Namespace(
        if_exists="drop",
        allow_destructive=False,
        table="dvt_sample_data",
        rows=None,
        connection_id="connection-id",
    )

    result = asyncio.run(fixtures.seed_table(args))

    assert result == {
        "success": False,
        "operation": "seed",
        "error": "truncate/drop requires --allow-destructive",
    }


def test_db_worker_timeout_is_structured(monkeypatch) -> None:
    fixtures = load_script("db_fixtures")
    args = argparse.Namespace(operation="check", timeout_sec=7)
    monkeypatch.setattr(fixtures.sys, "argv", ["db_fixtures.py", "check"])
    monkeypatch.setattr(
        fixtures.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("worker", 7)),
    )

    result = fixtures.run_bounded_worker(args)

    assert result["success"] is False
    assert result["timed_out"] is True


def test_changelog_append_preserves_existing_content(tmp_path) -> None:
    changelog = load_script("append_changelog")
    path = tmp_path / "AGENTS_CHANGELOGS.md"
    path.write_text("# Existing\n", encoding="utf-8")

    result = changelog.append_entry(
        tmp_path,
        "Добавлен project skill.\nУдален старый MCP.",
        now=datetime(2026, 9, 1, 12, 30, 0),
    )

    assert result["success"] is True
    assert path.read_text(encoding="utf-8") == (
        "# Existing\n\n"
        "### 2026-09-01 12:30:00\n"
        "- Добавлен project skill.\n"
        "- Удален старый MCP.\n"
    )
