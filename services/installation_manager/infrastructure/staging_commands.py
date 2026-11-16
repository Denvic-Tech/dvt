"""Bounded, quiet Linux subprocesses used by the staging path."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import TypeVar

from ..domain.operation_state import FailureReason
from ..domain.release_manifest import StagingError

T = TypeVar("T")
TOOL_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


@dataclass(frozen=True)
class RetryPolicy:
    total_seconds: float = 1800
    io_seconds: float = 300
    attempts: int = 3
    initial_delay: float = 1

    def __post_init__(self) -> None:
        if not (
            0 < self.total_seconds <= 86400
            and 0 < self.io_seconds <= 3600
            and 1 <= self.attempts <= 8
            and 0 <= self.initial_delay <= 60
        ):
            raise ValueError("Invalid staging retry policy")


class Deadline:
    def __init__(self, policy: RetryPolicy, temporary: Path | None = None) -> None:
        self.policy = policy
        self.temporary = temporary
        self.end = monotonic() + policy.total_seconds

    def remaining(self, reason: FailureReason) -> float:
        seconds = self.end - monotonic()
        if seconds <= 0:
            raise StagingError(
                reason,
                "The staging deadline expired",
                "Inspect the indicated service or storage and continue the same operation",
                retryable=True,
            )
        return seconds

    def retry(self, function: Callable[[], T], reason: FailureReason) -> T:
        delay = self.policy.initial_delay
        for attempt in range(1, self.policy.attempts + 1):
            self.remaining(reason)
            try:
                return function()
            except StagingError as error:
                if not error.retryable or attempt == self.policy.attempts:
                    raise
                if delay >= self.remaining(reason):
                    raise
                sleep(delay)
                delay *= 2
        raise AssertionError("Retry policy requires at least one attempt")


@dataclass(frozen=True)
class Output:
    code: int
    stdout: bytes
    stderr: bytes


def run_quietly(
    args: list[str],
    deadline: Deadline,
    reason: FailureReason,
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    limit: int = 4 * 1024 * 1024,
) -> Output:
    end = monotonic() + min(deadline.remaining(reason), deadline.policy.io_seconds)
    clean_env = {"PATH": TOOL_PATH, "LANG": "C.UTF-8", **(env or {})}
    if deadline.temporary is not None:
        clean_env["TMPDIR"] = str(deadline.temporary)
    if os.name != "posix":
        raise StagingError(
            reason, "Staging tools require a Linux executor", "Run staging on the Docker host"
        )
    try:
        proc = subprocess.Popen(
            args,
            env=clean_env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        raise StagingError(
            reason, "Could not start a staging tool", "Check the host tool and permissions"
        ) from None

    def time_left() -> float:
        seconds = end - monotonic()
        if seconds <= 0:
            raise subprocess.TimeoutExpired(args[0], 0)
        return seconds

    out, err = bytearray(), bytearray()
    assert proc.stdout is not None and proc.stderr is not None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ, out)
            selector.register(proc.stderr, selectors.EVENT_READ, err)
            while selector.get_map():
                for key, _ in selector.select(time_left()):
                    chunk = os.read(key.fd, 32768)
                    if not chunk:
                        selector.unregister(key.fd)
                        continue
                    key.data.extend(chunk)
                    if len(out) + len(err) > limit:
                        raise StagingError(
                            reason,
                            "A staging tool exceeded its output limit",
                            "Check the returned artifact or tool diagnostics on the host",
                        )
        return Output(proc.wait(timeout=time_left()), bytes(out), bytes(err))
    except subprocess.TimeoutExpired:
        raise StagingError(
            reason,
            "A staging command exceeded its deadline",
            "Check Linux host load and the affected network path, then continue the operation",
            retryable=reason
            in (FailureReason.DISTRIBUTOR_UNAVAILABLE, FailureReason.REGISTRY_UNAVAILABLE),
        ) from None
    finally:
        # Compose is a Docker CLI plugin. Kill its process group, including workers
        # that keep a pipe open after the command leader exits.
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=0.2)
        proc.stdout.close()
        proc.stderr.close()
