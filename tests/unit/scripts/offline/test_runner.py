from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
BASH = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")


def unix_path(path):
    text = str(path.resolve()).replace("\\", "/")
    return "/" + text[0].lower() + text[2:] if os.name == "nt" else text


@pytest.fixture
def bundle(tmp_path):
    directory = tmp_path / "bundle"
    directory.mkdir()
    for filename in ("install.sh", "update.sh", "offline-runtime.sh", "offline-config.py"):
        content = (ROOT / "scripts/offline" / filename).read_text(encoding="utf-8")
        (directory / filename).write_text(
            content.replace("{version}", "1.22.0"),
            encoding="utf-8",
            newline="\n",
        )
    (directory / "docker-compose.yaml").write_text("services: {}")
    (directory / "images").mkdir()
    (directory / "images/app.tar").write_bytes(b"image fixture")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$OFFLINE_TEST_LOG"
case "$1" in
  pull|build|login) echo "Network operation forbidden" >&2; exit 1 ;;
  run)
    [[ "$*" == *"--network none"* && "$*" == *"--pull never"* ]] || exit 2
    printf 'dvt\\n2\\nfalse\\n'
    ;;
  compose)
    if [[ "$*" == *"config --images"* ]]; then
      printf 'cr.distribution.denvic.tech/dvt/gateway:1.22.0\\npostgres:15.3-alpine\\n'
    fi
    ;;
esac
""",
        encoding="utf-8",
        newline="\n",
    )
    docker.chmod(0o755)
    sudo = binaries / "sudo"
    sudo.write_text('#!/usr/bin/env bash\nexec "$@"\n', encoding="utf-8", newline="\n")
    sudo.chmod(0o755)
    log = tmp_path / "commands.log"
    environment = dict(os.environ)
    environment["OFFLINE_TEST_LOG"] = unix_path(log)
    # Git Bash's startup converts the Windows PATH. Use POSIX syntax inside the command.
    environment["OFFLINE_TEST_BIN"] = unix_path(binaries)
    return directory, log, environment, tmp_path / "installed"


def run_bundle(bundle, filename, *args):
    directory, log, environment, target = bundle
    # Windows os.pathsep is unsuitable for Bash PATH; set it inside Bash explicitly.
    command = 'export PATH="$OFFLINE_TEST_BIN:$PATH"; bash "$1" -n --dir "$2" "${@:3}"'
    result = subprocess.run(
        [
            BASH,
            "-c",
            command,
            "offline-test",
            unix_path(directory / filename),
            unix_path(target),
            *args,
        ],
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    return result, log.read_text() if log.exists() else ""


@pytest.mark.skipif(not BASH or not Path(BASH).is_file(), reason="Bash is required")
def test_install_loads_images_and_runs_only_local_product_services(bundle):
    result, commands = run_bundle(bundle, "install.sh")
    assert result.returncode == 0, result.stderr
    assert "load -i" in commands
    assert "--network none" in commands
    assert "config --quiet" in commands
    assert "config --images" in commands
    up = next(line for line in commands.splitlines() if " up -d " in line)
    assert "--pull never" in up and "--no-build" in up
    assert "--scale task-worker=2" in up
    assert "installation_manager" not in up
    assert " pull " not in commands
    assert " down " not in commands


@pytest.mark.skipif(not BASH or not Path(BASH).is_file(), reason="Bash is required")
def test_update_without_existing_installation_stops_before_docker_commands(bundle):
    result, commands = run_bundle(bundle, "update.sh")
    assert result.returncode != 0
    assert "existing" in result.stderr
    assert commands == ""


@pytest.mark.skipif(not BASH or not Path(BASH).is_file(), reason="Bash is required")
def test_archive_cannot_be_relabelled_to_another_release(bundle):
    result, commands = run_bundle(bundle, "install.sh", "--version", "1.23.0")
    assert result.returncode != 0
    assert "match" in result.stderr
    assert commands == ""


@pytest.mark.skipif(not BASH or not Path(BASH).is_file(), reason="Bash is required")
def test_update_existing_installation_uses_local_images_and_keeps_data(bundle):
    target = bundle[3]
    target.mkdir()
    (target / ".env").write_text("DVT_VERSION=1.21.0\n", encoding="utf-8")
    data = target / "customer-data"
    data.write_bytes(b"persisted")
    result, commands = run_bundle(bundle, "update.sh")
    assert result.returncode == 0, result.stderr
    assert "--mode update" in commands
    assert "--pull never --no-build" in commands
    assert data.read_bytes() == b"persisted"
    assert " down " not in commands
