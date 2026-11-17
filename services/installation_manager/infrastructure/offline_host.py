"""Local Docker import and extension preparation for a verified offline bundle."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

from packaging.version import Version

from ..domain.operation_state import (
    ArtifactKind,
    FailureReason,
    Operation,
    OperationKind,
    OperationStage,
)
from ..domain.release_manifest import strict_json
from ..host_bootstrap import CONTROL
from .offline_bundle import (
    LOCAL_DOCKER_PACKAGES,
    MAX_INDEX,
    OfflineBundle,
    inspect_oci,
    verify_index,
)
from .operation_files import _require_private, _require_regular_file, sync_directory
from .operation_store import OperationStore
from .release_verification import MAX_MANIFEST_BYTES, TrustPolicy, invalid_package
from .staging_artifacts import read_artifact
from .staging_commands import Deadline, run_quietly
from .staging_docker import StagingDocker
from .staging_host import FilesystemBudget, check_filesystems, incompatible

OFFLINE_EXTENSION_ENV = "DVT_EXTENSION_OFFLINE_ONLY"
EXTENSION_ROLES = ("migrate", "gateway", "task-worker")


def local_trust(data: Path, default: dict | None = None) -> TrustPolicy:
    policy = read_artifact(data / CONTROL / "release-trust.json", MAX_INDEX)
    if policy is None and default is None:
        raise invalid_package("Install the trusted DVT release policy before using an offline bundle")
    return TrustPolicy.from_document(strict_json(policy) if policy is not None else default)


def read_bundle(
    store: OperationStore, bundle_id: UUID, trust: TrustPolicy, *, now: datetime | None = None,
) -> OfflineBundle:
    path = store.artifact_path(ArtifactKind.BUNDLE, bundle_id)
    try:
        for directory in (path.parent.parent, path.parent, path):
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise PermissionError
            _require_private(info, 0o700)
        raw = read_artifact(path / "bundle.json", MAX_INDEX)
        signature = read_artifact(path / "bundle.sig", 128)
        signed = read_artifact(path / "manifest.json", MAX_MANIFEST_BYTES)
        if raw is None or signature is None or signed is None:
            raise FileNotFoundError
    except OSError:
        raise invalid_package("The protected offline bundle is unavailable") from None
    bundle = verify_index(path, raw, signature, signed, trust, now=now)
    if bundle.id != bundle_id:
        raise invalid_package("The protected offline bundle does not match its admitted identity")
    return bundle


def host_distribution(path: Path) -> tuple[str, str]:
    release = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name in {"ID", "VERSION_ID"}:
            (release[name],) = shlex.split(value)
    try:
        return release["ID"], release["VERSION_ID"]
    except KeyError:
        raise incompatible("The offline executor could not determine the host distribution") from None


def check_bundle_host(
    bundle: OfflineBundle, os_release: Path, profiles: tuple[str, ...], platform: str
) -> None:
    if (
        host_distribution(os_release)
        != (bundle.index["distribution"], bundle.index["distribution_version"])
        or list(profiles) != bundle.index["profiles"]
        or platform != bundle.index["platform"]
    ):
        raise incompatible("The offline archive is for a different host or Compose profile")


def check_engine(info: dict) -> None:
    if ("driver-type", "io.containerd.snapshotter.v1") not in {
        tuple(entry) for entry in (info.get("DriverStatus") or ())
    }:
        raise incompatible("Offline import requires the Docker containerd image store")


def _verified_file(bundle: OfflineBundle, name: str) -> Path:
    path = bundle.directory / name
    try:
        info = path.lstat()
        _require_regular_file(info)
        descriptor = bundle.index["files"][name]
        if (
            info.st_size == descriptor["size"]
            and descriptor["digest"] == "sha256:" + _file_hash(path)
        ):
            return path
    except OSError:
        pass
    raise invalid_package("A protected offline artifact is missing or has changed")


def _file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_docker_packages(bundle: OfflineBundle, deadline: Deadline) -> list[str]:
    packages = {}
    for name in bundle.index["files"]:
        if not name.startswith("docker/"):
            continue
        path = _verified_file(bundle, name)
        result = run_quietly(
            ["dpkg-deb", "--field", str(path), "Package", "Architecture", "Version"],
            deadline, FailureReason.INVALID_PACKAGE, cwd=bundle.directory,
        )
        try:
            fields = dict(line.split(": ", 1) for line in result.stdout.decode("ascii").splitlines())
            package, arch, version = (fields[field] for field in ("Package", "Architecture", "Version"))
            distro, release_version = bundle.index["distribution"], bundle.index["distribution_version"]
            if (
                result.code or package in packages
                or arch not in {"amd64", "all"} or not name.split("/")[1].startswith(package + "_")
                or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]{0,127}", package)
                or (package in LOCAL_DOCKER_PACKAGES and (
                    arch != "amd64" or f"~{distro}.{release_version}~" not in version
                ))
            ):
                raise ValueError
            if package in {"docker-ce", "docker-compose-plugin"}:
                minimum = (
                    bundle.release.environment.min_docker if package == "docker-ce"
                    else bundle.release.environment.min_compose
                )
                numeric = version.split(":", 1)[-1].split("-", 1)[0]
                if Version(numeric) < Version(minimum):
                    raise ValueError
        except (KeyError, TypeError, ValueError):
            raise invalid_package("An offline Docker package does not match the platform") from None
        packages[package] = str(path)
    if bundle.index["kind"] == "install" and not packages.keys() >= LOCAL_DOCKER_PACKAGES:
        raise invalid_package("Required offline Docker packages are missing")
    return list(packages.values())


def install_local_docker(paths: list[str], cwd: Path, deadline: Deadline) -> None:
    # Empty package lists and disabled sources isolate resolution to installed
    # packages and the exact local packages from the signed archive.
    args = [
        "apt-get", "--no-download", "--no-remove", "--no-install-recommends", "-y",
        "-o", "Dir::Etc::sourcelist=/dev/null", "-o", "Dir::Etc::sourceparts=-",
    ]
    for operation in (["-s"], []):
        result = run_quietly(
            [*args, *operation, "install", *paths],
            deadline, FailureReason.INVALID_PACKAGE, cwd=cwd,
        )
        if result.code or re.search(rb"(?m)^Remv ", result.stdout):
            raise incompatible(
                "The local Docker packages cannot be installed with their available dependencies",
                "Supply the matching signed package set or prepare a compatible Docker host",
            )


def verify_oci_payloads(bundle: OfflineBundle) -> dict[str, tuple[Path, str, list[str]]]:
    expected = {}
    for reference, name in bundle.images.items():
        path = _verified_file(bundle, name)
        expected[reference] = (path, *inspect_oci(path, reference, bundle.index["platform"]))
    return expected


def import_offline_images(
    bundle: OfflineBundle, docker: StagingDocker, deadline: Deadline,
    *, verified: dict[str, tuple[Path, str, list[str]]] | None = None,
) -> None:
    platform = bundle.index["platform"]
    # Inspect the complete set before the first load, even if some images are already cached.
    expected = verify_oci_payloads(bundle) if verified is None else verified
    for reference, (path, config_id, diff_ids) in expected.items():
        if not docker.local_image(reference, platform, deadline):
            docker.load_image(path, deadline)
        if not docker.local_image(reference, platform, deadline):
            raise invalid_package("Docker did not expose the imported manifest digest")
        local = docker.inspect_image(reference, deadline)
        leaf = reference.split("@")[1]
        descriptor = local.get("Descriptor") or {}
        if (
            local.get("Id") not in {leaf, config_id}
            or descriptor.get("digest") != leaf
            or ((local.get("RootFS") or {}).get("Layers") or []) != diff_ids
        ):
            raise invalid_package("The imported Docker image identity differs from the signed image")


def check_offline_images(bundle: OfflineBundle, docker: StagingDocker, deadline: Deadline) -> None:
    for reference in bundle.images:
        if not docker.local_image(reference, bundle.index["platform"], deadline):
            raise invalid_package("An image required by offline staging is no longer local")


def _extension_entries(bundle: OfflineBundle, root: Path) -> dict[str, dict[str, Path]]:
    pending = root.parent / "installation" / "extensions_pending_deletions.json"
    if pending.exists() or pending.is_symlink():
        raise incompatible("Complete pending extension deletions before offline staging")
    packages = {name: {} for name in bundle.extensions}
    for name in bundle.index["files"]:
        if name.startswith("extensions/"):
            _, extension, rel = name.split("/", 2)
            packages[extension][rel] = _verified_file(bundle, name)
    if not root.exists() and not root.is_symlink():
        return packages
    if root.is_symlink() or not root.is_dir():
        raise invalid_package("The live extensions root is unsafe")
    for extension in root.iterdir():
        if extension.name.startswith("."):
            continue
        if extension.is_symlink() or not extension.is_dir() or extension.name not in packages:
            raise incompatible("An installed extension is outside the selected offline profile")
        # This profile permits new packages and wheels-only additions to the
        # exact existing version. It never replaces live extension code.
        approved = packages[extension.name]
        for path in extension.rglob("*"):
            if path.is_symlink():
                raise invalid_package("A live extension contains a symbolic link")
            if path.is_dir():
                continue
            rel = path.relative_to(extension).as_posix()
            if "__pycache__" in Path(rel).parts and path.suffix == ".pyc" and path.is_file():
                continue
            candidate = approved.get(rel)
            if (
                candidate is None or not path.is_file() or path.stat().st_nlink != 1
                or _file_hash(path) != _file_hash(candidate)
            ):
                raise incompatible("An installed extension differs from the signed offline profile")
        for rel in approved:
            path = extension / rel
            if not path.exists() and not rel.startswith(".dvt/wheels/"):
                raise incompatible("An installed extension is incomplete or a different version")
    return packages


def check_offline_extensions(
    bundle: OfflineBundle, root: Path, docker: StagingDocker, deadline: Deadline,
    *, platform: str,
) -> None:
    packages = _extension_entries(bundle, root)
    if not packages:
        return
    filesystem = root if root.exists() else root.parent
    while not filesystem.exists():
        filesystem = filesystem.parent
    check_filesystems([FilesystemBudget(
        "offline extension data", filesystem,
        sum(path.stat().st_size for files in packages.values() for path in files.values()),
        sum(len(files) for files in packages.values()) * 3,
    )])
    images = bundle.release.platforms[platform].images
    for reference in dict.fromkeys(images[role].reference for role in ("gateway", "task-worker")):
        docker.check_offline_extensions(
            reference, bundle.directory / "extensions", deadline
        )


def install_offline_extensions(bundle: OfflineBundle, root: Path) -> None:
    packages = _extension_entries(bundle, root)
    if not packages:
        return
    if not root.exists():
        root.mkdir()
        root.chmod(0o755)
    for name, files in packages.items():
        target = root / name
        if not target.exists():
            with tempfile.TemporaryDirectory(prefix=".offline-", dir=root) as temporary:
                staging = Path(temporary) / name
                _extension_directory(staging, Path(temporary))
                for rel, source in files.items():
                    path = staging / rel
                    _extension_directory(path.parent, staging)
                    _copy_extension_file(source, path)
                staging.rename(target)
                sync_directory(root)
        else:
            for rel, source in files.items():
                path = target / rel
                if not path.exists():
                    _extension_directory(path.parent, target)
                    _copy_extension_file(source, path)


def _extension_directory(directory: Path, root: Path) -> None:
    current = root
    for part in directory.relative_to(root).parts:
        current /= part
        if not current.exists():
            current.mkdir()
            current.chmod(0o755)


def _copy_extension_file(source: Path, target: Path) -> None:
    fd, name = tempfile.mkstemp(prefix=".offline-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as stream:
            shutil.copyfileobj(stream, output)
            os.fchmod(output.fileno(), 0o644)
            output.flush()
            os.fsync(output.fileno())
        Path(name).replace(target)
        sync_directory(target.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def offline_ready(
    operation: Operation, store: OperationStore, config: dict, plan: dict, trust: TrustPolicy,
    docker: StagingDocker, deadline: Deadline, *, now: datetime | None = None,
) -> OfflineBundle | None:
    if operation.request.bundle_id is None:
        return None
    bundle = read_bundle(store, operation.request.bundle_id, trust, now=now)
    if (
        bundle.pin != operation.request.release
        or bundle.index["kind"] != operation.request.kind.value
        or bundle.signed != read_artifact(
            store.artifact_path(ArtifactKind.STAGING, operation.id) / "manifest.json",
            MAX_MANIFEST_BYTES,
        )
    ):
        raise invalid_package("The staged offline bundle differs from the operation")
    os_release = Path("/run/dvt-host-os")
    if not os_release.is_file():
        os_release = Path("/etc/os-release")
    check_bundle_host(bundle, os_release, tuple(plan["profiles"]), plan["platform"])
    check_offline_images(bundle, docker, deadline)
    if operation.stage is OperationStage.PREPARED and operation.request.kind is OperationKind.UPDATE:
        check_offline_extensions(
            bundle, Path(config["data"]) / "extensions", docker, deadline, platform=plan["platform"]
        )
    return bundle
