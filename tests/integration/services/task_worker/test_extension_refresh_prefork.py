"""Real fork/signal tests; memory transport needs no external services."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="requires Linux prefork")


@pytest.mark.parametrize("mode", ["fork", "bootstrap", "ignore-term"])
def test_refresh_handles_child_startup_and_lost_sigterm(mode):
    probe = Path(__file__).with_name("_extension_refresh_prefork_probe.py")
    root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [sys.executable, str(probe), mode],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "queues restored, next job executed" in result.stdout
