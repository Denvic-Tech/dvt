from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _run_python(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_core_import_does_not_load_node_dsl_runtime() -> None:
    result = _run_python(
        """
import sys
import src.node_dsl.core.input_values  # noqa: F401

runtime_modules = [name for name in sys.modules if name.startswith("src.node_dsl.runtime")]
assert runtime_modules == [], runtime_modules
"""
    )

    assert result.returncode == 0, result.stderr


def test_legacy_file_connection_mixin_export_is_lazy() -> None:
    result = _run_python(
        """
import sys
import src.node_dsl as node_dsl

assert not any(name.startswith("src.node_dsl.runtime") for name in sys.modules)
legacy_mixin = node_dsl.FileConnectionInputMixin
from src.node_dsl.runtime.integrations.file_connection.mixin import FileConnectionInputMixin
assert legacy_mixin is FileConnectionInputMixin
"""
    )

    assert result.returncode == 0, result.stderr
