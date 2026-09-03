from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / ".codex" / "hooks"
STATE_PATH = HOOKS_DIR / ".unit_tests_stop_state.json"
LOG_PATH = HOOKS_DIR / "unit_tests_stop.log"


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=True)
    sys.stdout.write("\n")


def _load_state() -> dict[str, Any]:
    try:
        raw = STATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}

    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return state if isinstance(state, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _append_log(title: str, content: str) -> None:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(f"[{timestamp}] {title}\n")
        if content:
            stream.write(content.rstrip() + "\n")
        stream.write("\n")


def _git_status_fingerprint() -> str | None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _append_log("git status failed", (result.stderr or result.stdout).strip())
        return None

    lines = [
        line
        for line in result.stdout.splitlines()
        if ".codex/hooks/.unit_tests_stop_state.json" not in line
        and ".codex/hooks/unit_tests_stop.log" not in line
    ]
    normalized = "\n".join(lines).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _resolve_python() -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("DVT_VENV_PATH")
    if configured:
        configured_path = Path(configured)
        if configured_path.is_file():
            candidates.append(configured_path)
        else:
            candidates.extend(
                [
                    configured_path / "Scripts" / "python.exe",
                    configured_path / "bin" / "python",
                ]
            )

    candidates.extend(
        [
            REPO_ROOT / ".venv3.13" / "Scripts" / "python.exe",
            REPO_ROOT / ".venv" / "Scripts" / "python.exe",
            REPO_ROOT / "venv3.13" / "Scripts" / "python.exe",
            REPO_ROOT / "venv" / "Scripts" / "python.exe",
            REPO_ROOT / ".venv" / "bin" / "python",
            REPO_ROOT / "venv" / "bin" / "python",
            Path(sys.executable),
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return Path(sys.executable)


def _docker_available() -> tuple[bool, str]:
    docker_executable = shutil.which("docker")
    if not docker_executable:
        return False, "docker executable is not available in PATH."

    result = subprocess.run(
        [docker_executable, "info"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True, ""

    detail = (result.stderr or result.stdout).strip()
    return False, detail or "docker info failed."


def _run_unit_tests() -> tuple[int, str]:
    python_executable = _resolve_python()
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(REPO_ROOT)
        if not existing_pythonpath
        else os.pathsep.join([str(REPO_ROOT), existing_pythonpath])
    )

    result = subprocess.run(
        [str(python_executable), "-m", "scripts.docker.unit_tests"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    combined_output = "\n".join(
        part.strip()
        for part in [result.stdout, result.stderr]
        if part and part.strip()
    )
    return result.returncode, combined_output


def main() -> int:
    _read_payload()

    if sys.platform.startswith("win"):
        _emit({"continue": True})
        return 0

    fingerprint = _git_status_fingerprint()
    state = _load_state()
    if fingerprint and state.get("fingerprint") == fingerprint:
        _emit({"continue": True})
        return 0

    docker_ready, docker_detail = _docker_available()
    if not docker_ready:
        _append_log("unit tests skipped: docker unavailable", docker_detail)
        if fingerprint:
            _save_state(
                {
                    "fingerprint": fingerprint,
                    "result": "skipped_no_docker",
                    "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
        _emit(
            {
                "continue": True,
                "systemMessage": (
                    "Stop hook skipped dockerized unit tests because Docker is unavailable. "
                    f"See {LOG_PATH.as_posix()}."
                ),
            }
        )
        return 0

    exit_code, output = _run_unit_tests()
    _append_log(f"unit tests exit code: {exit_code}", output)
    if fingerprint:
        _save_state(
            {
                "fingerprint": fingerprint,
                "result": "passed" if exit_code == 0 else "failed",
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "exit_code": exit_code,
            }
        )

    if exit_code == 0:
        _emit({"continue": True})
        return 0

    _emit(
        {
            "continue": True,
            "systemMessage": (
                "Stop hook finished dockerized unit tests with failures. "
                f"See {LOG_PATH.as_posix()}."
            ),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
