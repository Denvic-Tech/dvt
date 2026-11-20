"""Observe the Docker host and account for staging storage."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from packaging.version import Version

from ..domain.operation_state import FailureReason
from ..domain.release_manifest import (
    Environment,
    ImageDescriptor,
    ResourceProfile,
    StagingError,
)
from .staging_commands import Deadline, run_quietly


def incompatible(
    problem: str, action: str = "Select a supported release or host profile"
) -> StagingError:
    return StagingError(FailureReason.INCOMPATIBLE_RELEASE, problem, action)


@dataclass(frozen=True)
class HostPaths:
    temporary: Path
    backup: Path
    containerd_root: Path | None = None
    os_release: Path = Path("/etc/os-release")

    def __post_init__(self) -> None:
        for path in (self.temporary, self.backup, self.containerd_root, self.os_release):
            if path is not None and not path.is_absolute():
                raise ValueError("Host observation paths must be absolute")


@dataclass(frozen=True)
class FilesystemBudget:
    role: str
    path: Path
    bytes: int
    inodes: int


def selected_profile(environment: Environment, profiles: tuple[str, ...]) -> ResourceProfile:
    if any(profile not in environment.profiles for profile in profiles):
        raise incompatible("The requested profile is absent from the release")
    requirements = [environment.base, *(environment.profiles[name] for name in profiles)]
    return ResourceProfile.model_validate(
        {
            field: max(getattr(profile, field) for profile in requirements)
            for field in ResourceProfile.model_fields
        }
        | {"max_task_workers": min(profile.max_task_workers for profile in requirements)}
    )


def check_platform(
    info: dict,
    compose_version: str,
    env: Environment,
    profile: ResourceProfile,
) -> str:
    try:
        if info["OSType"] != "linux":
            raise incompatible("Docker must be running in Linux container mode")
        docker_arch = info["Architecture"]
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(docker_arch, docker_arch)
        if Version(info["ServerVersion"]) < Version(env.min_docker) or Version(
            compose_version
        ) < Version(env.min_compose):
            raise incompatible("Docker Engine or Compose is below the release minimum")
        cpus = min(info["NCPU"], len(os.sched_getaffinity(0)))
        ram = min(info["MemTotal"], os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
        if cpus < profile.min_cpus or ram < profile.min_ram_bytes:
            raise incompatible(
                f"The host reports {cpus} CPUs and {ram} bytes RAM for this profile",
                f"Provide at least {profile.min_cpus} CPUs and {profile.min_ram_bytes} bytes RAM",
            )
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        raise incompatible(
            "Could not establish the Docker platform, version or host resources"
        ) from None
    return f"linux/{arch}"


def check_filesystems(budgets: list[FilesystemBudget]) -> None:
    grouped: dict[int, list[FilesystemBudget]] = {}
    for budget in budgets:
        try:
            path = budget.path.resolve(strict=True)
            if not path.is_dir():
                raise NotADirectoryError
            grouped.setdefault(path.stat().st_dev, []).append(budget)
        except OSError:
            raise StagingError(
                FailureReason.DISK_SPACE,
                f"Could not inspect the {budget.role} filesystem at {budget.path}",
                "Verify the local mount, directory and executor permissions",
            ) from None
    for group in grouped.values():
        roles = ", ".join(item.role for item in group)
        try:
            disk = os.statvfs(group[0].path)
        except OSError:
            raise StagingError(
                FailureReason.DISK_SPACE,
                f"Could not read filesystem capacity for {roles}",
                "Check the mount and executor permissions",
            ) from None
        deficit_bytes = sum(item.bytes for item in group) - disk.f_bavail * disk.f_frsize
        if deficit_bytes > 0:
            raise StagingError(
                FailureReason.DISK_SPACE,
                f"Filesystem {group[0].path} ({roles}) needs {deficit_bytes} more bytes",
                "Free or extend space on that filesystem while retaining the running and previous releases",
            )
        deficit_inodes = sum(item.inodes for item in group) - disk.f_favail
        if deficit_inodes > 0:
            raise StagingError(
                FailureReason.INODES,
                f"Filesystem {group[0].path} ({roles}) needs {deficit_inodes} more free inodes",
                "Free or extend inode capacity on that filesystem",
            )


def require_writable(path: Path, role: str) -> None:
    if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
        raise StagingError(
            FailureReason.DISK_SPACE,
            f"The {role} directory is unavailable for writes",
            "Check the expected directory, filesystem and owner permissions",
        )


def check_free_port(address: str, port: int, protocol: Literal["tcp", "udp"]) -> None:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    socket_type = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
    try:
        with socket.socket(family, socket_type) as probe:
            probe.bind((address, port))
    except OSError:
        raise StagingError(
            FailureReason.COMPOSE,
            f"Required host binding {address}:{port}/{protocol} is unavailable",
            "Select a free address and port or check host permissions",
        ) from None


def _copy_estimate(paths: set[Path], deadline: Deadline, cwd: Path) -> tuple[int, int]:
    totals = []
    for flag in ("--bytes", "--inodes"):
        result = run_quietly(
            ["du", flag, "--summarize", "--count-links", "--", *map(str, sorted(paths))],
            deadline,
            FailureReason.BACKUP,
            cwd=cwd,
        )
        try:
            if result.code:
                raise ValueError
            totals.append(sum(int(line.partition(b"\t")[0]) for line in result.stdout.splitlines()))
        except ValueError:
            raise StagingError(
                FailureReason.BACKUP,
                "Could not estimate persistent data needed for the recovery copy",
                "Check that the executor can inspect every selected persistent mount",
            ) from None
    return totals[0], totals[1]


def storage_budgets(
    info: dict,
    fs: HostPaths,
    data: Path,
    staging: Path,
    profile: ResourceProfile,
    images: list[ImageDescriptor],
    parallelism: int,
    persistent_paths: set[Path],
    deadline: Deadline,
) -> list[FilesystemBudget]:
    root = Path(info.get("DockerRootDir") or "")
    if not root.is_absolute():
        raise incompatible("Docker did not report its local data root")
    uses_containerd = ("driver-type", "io.containerd.snapshotter.v1") in {
        tuple(entry) for entry in (info.get("DriverStatus") or ())
    }
    if uses_containerd and (fs.containerd_root is None or not fs.containerd_root.is_absolute()):
        raise StagingError(
            FailureReason.DISK_SPACE,
            "The containerd image store's real data root is required",
            "Provide the Docker-managed or standalone containerd root from the local daemon configuration",
        )
    docker_bytes = profile.docker_reserve_bytes
    compressed = sum(image.compressed_bytes for image in images)
    unpacked = sum(image.unpacked_bytes for image in images)
    unpacked_inode_count = sum(image.unpacked_inodes for image in images)
    # Existing images (including previous releases) already consume space in statvfs.
    # Missing images reserve full layers, avoiding optimistic deductions for shared layers.
    # Reserve the largest concurrent downloads again for transient compressed content.
    transient = sum(
        sorted((image.compressed_bytes for image in images), reverse=True)[:parallelism]
    )
    reserve = profile.reserve_inodes
    budgets = [
        FilesystemBudget("Docker", root, docker_bytes, reserve),
        FilesystemBudget("data", data, profile.data_reserve_bytes, reserve),
        FilesystemBudget("staging", staging, profile.temporary_bytes, reserve),
        FilesystemBudget(
            "temporary download", fs.temporary, profile.temporary_bytes + transient, reserve
        ),
    ]
    if uses_containerd:
        assert fs.containerd_root is not None
        image_bytes = compressed + unpacked + transient
        budgets.append(
            FilesystemBudget(
                "containerd", fs.containerd_root, image_bytes, unpacked_inode_count + reserve
            )
        )
    else:
        budgets.append(
            FilesystemBudget(
                "Docker image store",
                root,
                compressed + unpacked + transient,
                unpacked_inode_count + reserve,
            )
        )
    if persistent_paths:
        copy_size, copy_inodes = _copy_estimate(persistent_paths, deadline, staging)
        budgets.append(
            FilesystemBudget(
                "backup", fs.backup, copy_size + profile.data_reserve_bytes, copy_inodes + reserve
            )
        )
        for path in sorted(persistent_paths):
            if path != data:
                budgets.append(
                    FilesystemBudget("persistent data", path, profile.data_reserve_bytes, reserve)
                )
    return budgets
