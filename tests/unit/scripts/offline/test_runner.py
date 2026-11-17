from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
BASH = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")


def unix_path(path: Path) -> str:
    text = str(path.resolve()).replace("\\", "/")
    return "/" + text[0].lower() + text[2:] if os.name == "nt" else text


@pytest.mark.skipif(not BASH or not Path(BASH).is_file(), reason="Bash is required")
@pytest.mark.parametrize("entrypoint", ("install", "update"))
def test_offline_entrypoint_delegates_to_the_verified_lifecycle(tmp_path, entrypoint):
    interpreter = tmp_path / "python-stub"
    interpreter.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    interpreter.chmod(0o755)
    script = ROOT / "scripts/offline" / f"{entrypoint}.sh"
    arguments = ["--dir", "/srv/dvt", "--bundle", "/media/signed archive.tar.gz"]
    result = subprocess.run(
        [BASH, unix_path(script), *arguments],
        env={**os.environ, "DVT_OFFLINE_PYTHON": unix_path(interpreter)},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "-m", "services.installation_manager.application.offline_bundles", entrypoint, *arguments,
    ]
