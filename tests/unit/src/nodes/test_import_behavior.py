import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def test_import_category_does_not_eager_import_nodes() -> None:
    # Use a fresh interpreter without changing modules held by other tests.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib
import sys

importlib.import_module("src.nodes.transform")
loaded = {
    name
    for name in sys.modules
    if name.startswith("src.nodes.transform.")
}
assert loaded == set(), loaded
""",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_single_node_does_not_eager_import_category() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib
import sys

module = importlib.import_module("src.nodes.transform.df_join")
assert module.DataFrameJoin.__module__ == "src.nodes.transform.df_join.node"
assert "src.nodes.transform.df_join.node" in sys.modules
assert "src.nodes.transform.df_filter" not in sys.modules
assert "src.nodes.transform.df_union" not in sys.modules
""",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
