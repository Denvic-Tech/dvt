from __future__ import annotations

import platform
import textwrap

import pytest


@pytest.mark.docker_required
@pytest.mark.skipif(
    platform.system() != "Linux",
    reason="Real nofile stress scenario is executed only on Linux hosts.",
)
def test_docker_container_hits_emfile_with_low_nofile_limit() -> None:
    docker = pytest.importorskip("docker")

    try:
        client = docker.from_env()
        client.ping()
    except docker.errors.DockerException as exc:
        pytest.skip(f"Docker daemon is unavailable: {exc}")

    script = textwrap.dedent(
        """
        import errno
        import sys

        handles = []
        emfile_triggered = False
        try:
            for idx in range(4096):
                try:
                    handles.append(open(f"/tmp/emfile_{idx}.tmp", "w"))
                except OSError as exc:
                    if exc.errno == errno.EMFILE:
                        print("EMFILE_TRIGGERED")
                        emfile_triggered = True
                        break
                    raise
        finally:
            for handle in handles:
                try:
                    handle.close()
                except Exception:
                    pass

        if not emfile_triggered:
            print("EMFILE_NOT_TRIGGERED")
            sys.exit(2)
        """
    )

    container = client.containers.run(
        image="python:3.13-alpine",
        command=["python", "-c", script],
        detach=True,
        remove=False,
        ulimits=[docker.types.Ulimit(name="nofile", soft=64, hard=64)],
    )

    try:
        wait_result = container.wait(timeout=90)
        status_code = (
            int(wait_result.get("StatusCode", 1))
            if isinstance(wait_result, dict)
            else int(wait_result)
        )
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
    finally:
        container.remove(force=True)

    assert status_code == 0, logs
    assert "EMFILE_TRIGGERED" in logs, logs
