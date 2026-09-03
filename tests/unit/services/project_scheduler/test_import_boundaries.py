from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def test_project_scheduler_import_does_not_require_botocore() -> None:
    script = """
import builtins

real_import = builtins.__import__


def guarded_import(name, *args, **kwargs):
    if name == "botocore" or name.startswith("botocore."):
        raise ModuleNotFoundError("botocore import is forbidden for Project Scheduler")
    return real_import(name, *args, **kwargs)


builtins.__import__ = guarded_import
import services.project_scheduler.main  # noqa: F401
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
