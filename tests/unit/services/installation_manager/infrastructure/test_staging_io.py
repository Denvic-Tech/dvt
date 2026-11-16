from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from services.installation_manager.domain.operation_state import FailureReason
from services.installation_manager.domain.release_manifest import StagingError
from services.installation_manager.infrastructure import staging_docker, staging_host
from services.installation_manager.infrastructure.staging_commands import (
    Deadline,
    Output,
    RetryPolicy,
    run_quietly,
)
from services.installation_manager.infrastructure.staging_docker import StagingDocker
from services.installation_manager.infrastructure.staging_downloads import (
    classify_io_error,
    https_origin,
)
from services.installation_manager.infrastructure.staging_host import (
    FilesystemBudget,
    check_filesystems,
)

OK_IMAGE = "docker.io/library/example@sha256:" + "a" * 64


@pytest.mark.parametrize(
    ("description", "reason", "retryable"),
    [
        (b"x509: certificate signed by unknown authority", FailureReason.TLS, False),
        (b"net/http: TLS handshake timeout", FailureReason.REGISTRY_UNAVAILABLE, True),
        (b"read: connection reset by peer", FailureReason.REGISTRY_UNAVAILABLE, True),
        (b"lookup registry: no such host", FailureReason.REGISTRY_UNAVAILABLE, False),
        (
            b"unauthorized: access denied (password=SECRET)",
            FailureReason.REGISTRY_UNAVAILABLE,
            False,
        ),
        (b"write /var/lib/containerd: no space left on device", FailureReason.DISK_SPACE, False),
        (b"manifest unknown", FailureReason.INVALID_PACKAGE, False),
    ],
)
def test_failure_classes_are_safe_and_retryable_only_for_transient_errors(
    description, reason, retryable
):
    error = classify_io_error(FailureReason.REGISTRY_UNAVAILABLE, description)
    assert error.reason is reason
    assert error.retryable is retryable
    assert "SECRET" not in str(error)


@pytest.mark.parametrize(
    "url",
    ["http://repo.test/file", "https://u:p@repo.test/file", "https://repo.test/file?key=secret"],
)
def test_release_url_disallows_cleartext_or_tokens(url):
    with pytest.raises(StagingError) as error:
        https_origin(url)
    assert error.value.reason is FailureReason.INVALID_PACKAGE
    assert url not in str(error.value)


def test_registry_pull_uses_bounded_retry_on_actual_cli_failure(monkeypatch, tmp_path):
    attempts = []

    def run(args, deadline, reason, **_kwargs):
        attempts.append(args)
        if args[5:7] == ["image", "pull"]:
            first = sum(cmd[5:7] == ["image", "pull"] for cmd in attempts) == 1
            return Output(1, b"", b"connection reset by peer") if first else Output(0, b"", b"")
        return Output(
            0,
            b'[{"Os":"linux","Architecture":"amd64","RepoDigests":["' + OK_IMAGE.encode() + b'"]}]',
            b"",
        )

    monkeypatch.setattr(staging_docker, "run_quietly", run)
    docker = StagingDocker(tmp_path, tmp_path)
    docker.pull(OK_IMAGE, "linux/amd64", Deadline(RetryPolicy(initial_delay=0)))
    assert len(attempts) == 3
    assert attempts[0] == attempts[1]
    assert attempts[0][-3:] == ["--platform", "linux/amd64", OK_IMAGE]


def test_compose_json_preserves_literal_dollar_signs(monkeypatch, tmp_path):
    secret = "fixture-only-${literal}-$-$$"
    service = {"environment": {"DVT_AI_MCP_INTERNAL_SECRET": secret.replace("$", "$$")}}
    command_result = Output(
        0, json.dumps({"services": {"gateway": service, "dvt-ai-mcp": service}}).encode(), b""
    )
    monkeypatch.setattr(staging_docker, "run_quietly", lambda *_args, **_kwargs: command_result)
    docker = StagingDocker(tmp_path, tmp_path)
    model = docker.config(
        tmp_path / "compose.yaml", "fixture", ("ai-mcp",), {}, Deadline(RetryPolicy())
    )
    assert all(
        item["environment"]["DVT_AI_MCP_INTERNAL_SECRET"] == secret
        for item in model["services"].values()
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process groups and /proc")
@pytest.mark.parametrize("parent_exits", [True, False])
def test_deadline_kills_silent_compose_plugin_and_its_descendant(tmp_path, parent_exits):
    pid_file = tmp_path / "worker.pid"
    child = f"from pathlib import Path; import os,time; Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        f"time.sleep({0 if parent_exits else 60})"
    )
    start = monotonic()
    with pytest.raises(StagingError, match="exceeded its deadline"):
        run_quietly(
            [sys.executable, "-c", parent],
            Deadline(RetryPolicy(total_seconds=0.6)),
            FailureReason.COMPOSE,
            cwd=tmp_path,
        )
    assert monotonic() - start < 2
    worker = Path("/proc") / pid_file.read_text() / "stat"
    # The Linux scheduler may report the child as runnable briefly after killpg.
    end = monotonic() + 0.3
    while monotonic() < end:
        try:
            if worker.read_text().split()[2] == "Z":
                return
        except FileNotFoundError:
            return
        sleep(0.01)
    pytest.fail("The timed-out process group still has a live descendant")


@pytest.mark.skipif(not hasattr(os, "statvfs"), reason="Linux filesystem capacity")
@pytest.mark.parametrize(
    ("bytes_free", "inodes_free", "reason", "missing"),
    [
        (74, 2, FailureReason.DISK_SPACE, "1 more bytes"),
        (100, 1, FailureReason.INODES, "1 more free inodes"),
    ],
)
def test_shared_filesystem_aggregates_reservation_and_reports_deficit(
    tmp_path, monkeypatch, bytes_free, inodes_free, reason, missing
):
    docker, containerd = (tmp_path / "docker", tmp_path / "containerd")
    docker.mkdir()
    containerd.mkdir()
    monkeypatch.setattr(
        staging_host.os,
        "statvfs",
        lambda _path: SimpleNamespace(
            f_bavail=bytes_free,
            f_frsize=1,
            f_favail=inodes_free,
        ),
    )
    with pytest.raises(StagingError) as error:
        check_filesystems(
            [
                FilesystemBudget("Docker", docker, 25, 1),
                FilesystemBudget("containerd", containerd, 50, 1),
            ]
        )
    assert error.value.reason is reason
    assert "Docker, containerd" in str(error.value)
    assert missing in str(error.value)
