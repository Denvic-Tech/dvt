"""Protected host files and the process-owned executor lock."""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from ..domain.operation_state import OwnershipConflict

_database_creation_lock = Lock()


def sync_directory(path: Path) -> None:
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _require_private(info: os.stat_result, mode: int) -> None:
    if os.name == "posix" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode):
        raise PermissionError(f"Installation state requires owner-only mode {mode:o}")


def prepare_directory(path: Path) -> Path:
    path = path.parent.resolve(strict=os.name == "posix") / path.name
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise PermissionError("Installation state must be a real directory")
    _require_private(info, 0o700)
    sync_directory(path.parent)
    return path


def _require_regular_file(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PermissionError("Installation state requires a regular file with one link")
    _require_private(info, 0o600)


def prepare_database(path: Path) -> None:
    # Closing a separate descriptor for an open SQLite database would release POSIX
    # record locks held by other SQLite connections in this process.
    with _database_creation_lock:
        if not path.exists():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
        _require_regular_file(path.lstat())


@contextmanager
def private_file(path: Path) -> Iterator[int]:
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        _require_regular_file(info)
        if not os.path.samestat(info, path.lstat()):
            raise PermissionError("Installation state file changed while opening")
        yield fd
    finally:
        os.close(fd)


@contextmanager
def executor_lock(path: Path) -> Iterator[None]:
    with private_file(path) as fd:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                raise OwnershipConflict("The instance executor lock is held") from None
            try:
                yield
            finally:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise OwnershipConflict("The instance executor lock is held") from None
            owner_pid = os.getpid()
            try:
                yield
            finally:
                if os.getpid() == owner_pid:
                    fcntl.flock(fd, fcntl.LOCK_UN)
