"""Prepare a signed archive for the ordinary DVT installation operation."""

from __future__ import annotations

import argparse
import errno
import json
import os
import platform
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from uuid import UUID, uuid4

from packaging.version import Version

from ..domain.operation_state import (
    ArtifactKind,
    InstanceIdentity,
    OperationConflict,
    OperationKind,
    OperationRequest,
    OperationStage,
    OwnershipConflict,
    ReleasePin,
)
from ..domain.release_manifest import StagingError, canonical_json, digest_of, strict_json
from ..host_bootstrap import (
    CONTROL,
    UNIT_DIR,
    atomic_write,
    bootstrap_with_lock,
    check_port,
    check_project,
    docker_ready,
    load_host,
    safe_path,
)
from ..infrastructure.application_host import DATABASE_ID
from ..infrastructure.maintenance_host import ComposeMaintenanceHost
from ..infrastructure.offline_bundle import MAX_INDEX, OfflineBundle, extract_bundle
from ..infrastructure.offline_host import (
    check_bundle_host,
    check_docker_packages,
    check_engine,
    check_offline_extensions,
    host_distribution,
    import_offline_images,
    install_local_docker,
    local_trust,
    read_bundle,
    verify_oci_payloads,
)
from ..infrastructure.operation_files import sync_directory
from ..infrastructure.operation_store import OperationStore
from ..infrastructure.release_verification import TrustPolicy, invalid_package
from ..infrastructure.staging_artifacts import (
    CONFIG_KEY,
    MAX_CONFIG_BYTES,
    artifact_directory,
    read_artifact,
    save_config,
    validate_config,
)
from ..infrastructure.staging_commands import Deadline, RetryPolicy
from ..infrastructure.staging_compose import (
    COMPOSE_LIMIT,
    ObservedRelease,
    check_model,
    compare_project,
    effective_config,
    validate_template,
)
from ..infrastructure.staging_docker import StagingDocker, image_references
from ..infrastructure.staging_host import (
    FilesystemBudget,
    HostPaths,
    check_filesystems,
    check_platform,
    incompatible,
    selected_profile,
    storage_budgets,
)
from .application_apply import _validate_runtime
from .legacy_adopt import _containers
from .verified_staging import VerifiedStaging


def _preparer_version() -> str:
    project = Path(__file__).parents[3] / "pyproject.toml"
    return tomllib.loads(project.read_text(encoding="utf-8"))["project"]["version"]


class OfflinePreparationError(RuntimeError):
    """An admitted operation failed to reach verified staging."""


class LocalOnly:
    def get(self, *_args, **_settings):
        raise invalid_package("An offline operation cannot download a release artifact")


def _configuration(config: dict, store: OperationStore, deadline: Deadline, local: StagingDocker):
    data = Path(config["data"])
    content = read_artifact(data / CONTROL / "current-release.json", MAX_INDEX)
    if content is None:
        raise incompatible("Adopt the observed supported source before preparing an offline update")
    current = strict_json(content)
    environment = read_artifact(data / ".env", MAX_CONFIG_BYTES)
    compose = read_artifact(data / "docker-compose.yaml", COMPOSE_LIMIT * 8)
    if (
        current["format_version"] != 1 or current["instance"] != config["instance"]
        or environment is None or digest_of(environment) != current["config_digest"]
        or compose is None or digest_of(compose) != current["compose_digest"]
        or store.identity().instance_id != UUID(config["instance"])
    ):
        raise incompatible("The observed source disagrees with the committed release and settings")
    roles = _containers(config["project"])
    (gateway,) = roles.get("gateway", ())
    (postgres,) = roles.get("postgres", ())
    if (
        not gateway["State"]["Running"] or not postgres["State"]["Running"]
        or any(row["State"]["Running"] for row in roles.get("migrate", ()))
    ):
        raise incompatible("The source application and PostgreSQL must be stable")
    inspect = local.inspect_image(gateway["Image"], deadline)
    pg = postgres["Id"]
    revision = ComposeMaintenanceHost.sql(pg, "SELECT version_num FROM alembic_version")
    if (
        inspect is None or current["images"]["gateway"] not in image_references(inspect)
        or revision != current["revision"]
        or ComposeMaintenanceHost.sql(pg, DATABASE_ID) != current["database"]
    ):
        raise incompatible("The source Gateway or database differs from the committed release")
    pin = ReleasePin(current["release_id"], current["manifest_digest"])
    observed = ObservedRelease(
        version=current["version"], revision=revision, pin=pin,
        images={name: ref for name, ref in current["images"].items() if name != "migrate"},
    )
    # Compose reads canonical and adopted legacy dotenv syntax without shell evaluation.
    result = local._checked(
        [
            "compose", "--project-directory", str(data), "--project-name", config["project"],
            "--env-file", str(data / ".env"), "--file", str(data / "docker-compose.yaml"),
            "config", "--environment",
        ],
        deadline, "read committed deployment settings",
    )
    values = {}
    for line in result.decode("utf-8").splitlines():
        name, equal, value = line.partition("=")
        if equal and CONFIG_KEY.fullmatch(name):
            values[name] = value
    validate_config(values)
    return observed, values


def _publish(bundle: OfflineBundle, store: OperationStore, trust: TrustPolicy) -> None:
    path = artifact_directory(store, ArtifactKind.BUNDLE, bundle.id)
    try:
        bundle.directory.rename(path)
    except OSError as error:
        if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
            raise
        existing = read_bundle(store, bundle.id, trust)
        if existing.index != bundle.index:
            raise invalid_package("The admitted offline bundle conflicts with the protected copy") from None
    else:
        sync_directory(path.parent)


def _preflight_fresh(args, data: Path, bundle: OfflineBundle, values: dict[str, str]) -> None:
    if not Path("/run/systemd/system").is_dir():
        raise incompatible("The offline installation host must run systemd")
    if args.config is None or not all((args.cert, args.key, args.ca, args.public_url)):
        raise ValueError("Supply --config, --public-url and local --cert, --key and --ca")
    identity = InstanceIdentity(
        uuid4(), str(data), args.project or "dvt", "127.0.0.1", args.port or 8888,
        args.public_url,
    )
    if (
        (data.exists() and any(
            path != bundle.directory
            and (not path.name.startswith(".bootstrap-partial-") or not path.is_dir())
            for path in data.iterdir()
        ))
        or UNIT_DIR.joinpath(f"dvt-bootstrap-{identity.compose_project}.service").exists()
    ):
        raise incompatible("The offline target is not a fresh installation")
    check_port(identity.manager_address, identity.manager_port)
    release = bundle.release
    if Version(_preparer_version()) < Version(release.compatibility.minimum_preparer_version):
        raise incompatible("The current preparer is too old for this offline release")
    request = OperationRequest(OperationKind.INSTALL, bundle.pin, bundle_id=bundle.id)
    prepared, profiles = effective_config(values, identity, request, release.version)
    resources = selected_profile(release.environment, profiles)
    check_bundle_host(bundle, Path("/etc/os-release"), profiles, "linux/amd64")
    if (
        len(os.sched_getaffinity(0)) < resources.min_cpus
        or os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") < resources.min_ram_bytes
    ):
        raise incompatible("Host CPU or memory does not satisfy the offline profile")
    if release.channel == "rc" and values.get("DVT_ALLOW_PRERELEASE", "").lower() != "true":
        raise incompatible("An offline release candidate requires explicit consent")

    deadline = Deadline(RetryPolicy(), bundle.directory)
    local = StagingDocker(bundle.directory, Path("/root/.docker"))
    verified = verify_oci_payloads(bundle)
    packages = check_docker_packages(bundle, deadline)
    if not docker_ready():
        if not args.install_docker:
            raise incompatible("Docker is unavailable. Use --install-docker for the local packages")
        disk = Path("/var/lib")
        images = {
            image.reference: image for image in release.platforms["linux/amd64"].images.values()
        }
        check_filesystems([FilesystemBudget(
            "offline Docker and application", disk,
            sum(image.compressed_bytes + image.unpacked_bytes for image in images.values())
            + sum(Path(path).stat().st_size for path in packages) * 2
            + resources.docker_reserve_bytes,
            sum(image.unpacked_inodes for image in images.values()) + resources.reserve_inodes,
        )])
        install_local_docker(packages, bundle.directory, deadline)
    check_project(identity.compose_project)
    info = local.info(deadline)
    check_engine(info)
    containerd = safe_path(args.containerd_root or "/var/lib/containerd")
    paths = HostPaths(
        bundle.directory, bundle.directory, containerd_root=containerd,
    )
    detected = check_platform(
        info, local.compose_version(deadline), paths.os_release, release.environment, resources
    )
    distribution = release.platforms[detected]
    compose = bundle.directory / "compose.yaml"
    validate_template(bundle.verify_asset("compose.yaml"))
    full = local.config(compose, identity.compose_project, ("*",), prepared, deadline)
    check_model(full, identity, distribution, prepared, active=False)
    current = local.config(compose, identity.compose_project, profiles, prepared, deadline)
    check_model(current, identity, distribution, prepared, active=True)
    _validate_runtime(current)
    compare_project(current, identity, prepared, local, None, deadline)
    missing = {
        image.reference: image for image in distribution.images.values()
        if not local.local_image(image.reference, detected, deadline)
    }
    check_filesystems(storage_budgets(
        info, paths, data if data.exists() else data.parent, bundle.directory, resources,
        list(missing.values()), 1, set(), deadline,
    ))
    import_offline_images(bundle, local, deadline, verified=verified)
    check_offline_extensions(bundle, data / "extensions", local, deadline, platform=detected)

    manager = distribution.images["installation_manager"].reference
    local.check_offline_executor(manager, deadline)
    bootstrap_with_lock(argparse.Namespace(
        dir=str(data), project=identity.compose_project, port=identity.manager_port,
        public_url=identity.public_url, manager=manager, candidate=manager, executor=manager,
        cert=args.cert, key=args.key, ca=args.ca, containerd_root=str(containerd),
        temporary=args.temporary, backup=args.backup, non_interactive=True,
        release_catalog_config=None, new_pairing_token=False, local_images=True, quiet=True,
    ))
    atomic_write(data / CONTROL / "release-trust.json", canonical_json(_trust_file(args.trust).as_document()))


def _trust_file(path: str | None) -> TrustPolicy:
    if path is None:
        raise ValueError("Supply the independently trusted release policy with --trust")
    return TrustPolicy.from_document(strict_json(_read_input(Path(path), MAX_INDEX)))


def _read_input(path: Path, maximum: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("An offline CLI input exceeds the size limit")
    return data


def _prepare(
    args, config: dict, trust: TrustPolicy, bundle: OfflineBundle | None, values: dict[str, str],
) -> UUID:
    data = Path(config["data"])
    store = OperationStore.for_host(data)
    local = StagingDocker(data, Path("/root/.docker"))
    paths = HostPaths(
        Path(config["temporary"]), Path(config["backup"]),
        containerd_root=Path(config["containerd_root"]),
    )
    deadline = Deadline(RetryPolicy(), paths.temporary)
    active = store.active()
    operation = store.get(args.operation_id) if args.operation_id is not None else active
    if args.operation_id is not None and operation is None:
        raise ValueError("Unknown offline operation")
    if operation is not None and (
        operation.request.bundle_id is None
        or (bundle is not None and bundle.id != operation.request.bundle_id)
    ):
        raise OperationConflict(operation.id)

    if operation is not None:
        if operation.request.kind.value != args.action:
            raise OperationConflict(operation.id)
        if operation.stage not in {
            OperationStage.ADMITTED, OperationStage.PREPARING, OperationStage.PREPARED,
        }:
            return operation.id

    local.check_offline_executor(config["executor"], deadline)
    observed = None
    if args.action == "update":
        observed, values = _configuration(config, store, deadline, local)
    if operation is None:
        assert bundle is not None
        if args.confirm_rc:
            values["DVT_ALLOW_PRERELEASE"] = "true"
        if bundle.release.channel == "rc" and values.get("DVT_ALLOW_PRERELEASE") != "true":
            raise incompatible("Use --confirm-rc to prepare the selected release candidate")
        request = OperationRequest(
            OperationKind(args.action), bundle.pin,
            bundle_id=bundle.id, config_id=save_config(store, values),
        )
        _publish(bundle, store, trust)
        operation = store.admit(request, idempotency_key=f"offline-{uuid4()}")
    elif args.config is not None:
        raise ValueError("Continue the same operation with its saved configuration and ID")
    manager = read_artifact(data / CONTROL / "current-manager", MAX_INDEX)
    try:
        staged = VerifiedStaging(
            store, trust, LocalOnly(), local, paths, _preparer_version(),
            http_manager=config.get("manager_http") is True,
        ).prepare(
            operation.id, "", observed=observed, applied=observed.pin if observed else None,
            bootstrap_image=manager.decode().strip() if manager is not None else None,
        )
    except (StagingError, OwnershipConflict) as error:
        raise OfflinePreparationError(f"{error} Operation ID {operation.id}") from None
    return staged.operation_id


def run(args) -> dict:
    data = safe_path(args.dir)
    if args.operation_id is not None and args.bundle is not None:
        raise ValueError("Select either the archive or the existing operation ID")
    if args.operation_id is None and args.bundle is None:
        raise ValueError("Supply --bundle or continue with --operation-id")
    existing = (data / CONTROL / "host.json").is_file()
    config = load_host(data) if existing else None
    if config:
        trust = local_trust(data, (config.get("release_catalog") or {}).get("trust"))
    else:
        trust = _trust_file(args.trust)
    if args.operation_id is not None:
        if config is None or args.action not in {"install", "update"}:
            raise ValueError("An installation or update operation requires an existing instance")
        return {"operation_id": str(_prepare(args, config, trust, None, {}))}

    parent = data if existing or data.is_dir() else data.parent
    with tempfile.TemporaryDirectory(prefix=".bootstrap-partial-", dir=parent) as temporary:
        directory = Path(temporary)
        bundle = extract_bundle(Path(args.bundle), directory, trust)
        if args.version is not None and Version(args.version) != Version(bundle.release.version):
            raise invalid_package("The offline archive does not match the requested version")
        if host_distribution(Path("/etc/os-release")) != (
            bundle.index["distribution"], bundle.index["distribution_version"],
        ):
            raise incompatible("The offline archive is for a different host distribution")
        if args.action in {"verify", "restore-images"}:
            deadline = Deadline(RetryPolicy(), directory)
            verified = verify_oci_payloads(bundle)
            check_docker_packages(bundle, deadline)
            if args.action == "restore-images":
                local = StagingDocker(directory, Path("/root/.docker"))
                info = local.info(deadline)
                check_engine(info)
                containerd = args.containerd_root or (
                    config["containerd_root"] if config else "/var/lib/containerd"
                )
                paths = HostPaths(directory, directory, Path(containerd))
                platform_release = bundle.release.platforms[bundle.index["platform"]]
                resources = selected_profile(
                    bundle.release.environment, tuple(bundle.index["profiles"])
                )
                platform = check_platform(
                    info, local.compose_version(deadline), paths.os_release,
                    bundle.release.environment, resources,
                )
                missing = {
                    image.reference: image for image in platform_release.images.values()
                    if not local.local_image(image.reference, platform, deadline)
                }
                check_filesystems(storage_budgets(
                    info, paths, parent, directory, resources, list(missing.values()),
                    1, set(), deadline,
                ))
                import_offline_images(bundle, local, deadline, verified=verified)
            return {"release_id": bundle.pin.release_id, "manifest_digest": bundle.pin.manifest_digest,
                    "bundle_id": str(bundle.id)}
        if args.action != bundle.index["kind"]:
            raise invalid_package("The archive has a different installation operation kind")
        values = {}
        if args.action == "install" and args.config is not None:
            values = strict_json(_read_input(Path(args.config), MAX_CONFIG_BYTES))
            validate_config(values)
        if args.confirm_rc:
            values["DVT_ALLOW_PRERELEASE"] = "true"
        if not config:
            if args.action != "install":
                raise incompatible("An offline update requires an established installation")
            _preflight_fresh(args, data, bundle, values)
            config = load_host(data)
        elif args.action == "install" and args.config is None:
            raise ValueError("Supply the protected initial installation configuration or operation ID")
        elif args.action == "update" and args.config is not None:
            raise ValueError("Offline update uses the committed source settings")
        return {"operation_id": str(_prepare(args, config, trust, bundle, values))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "update", "verify", "restore-images"])
    parser.add_argument("--bundle")
    parser.add_argument("--operation-id", type=UUID)
    parser.add_argument("--dir", "--host-dir", default="/var/lib/dvt")
    for key in (
        "trust", "config", "project", "public-url", "cert", "key", "ca", "containerd-root",
        "temporary", "backup",
    ):
        parser.add_argument(f"--{key}")
    parser.add_argument("--port", type=int)
    parser.add_argument("--version", help="Require the signed release to match this version")
    parser.add_argument("-n", "--non-interactive", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--install-docker", action="store_true")
    parser.add_argument("--confirm-rc", action="store_true")
    args = parser.parse_args()
    try:
        os.umask(0o077)
        if os.geteuid() or not sys.platform.startswith("linux") or platform.machine() != "x86_64":
            raise ValueError("Offline DVT preparation requires root on Linux amd64")
        sys.stdout.write(json.dumps(run(args), sort_keys=True) + "\n")
    except OperationConflict as error:
        sys.stderr.write(f"{error}. Operation ID {error.operation_id}\n")
        return 1
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        # Tool stderr and raw input can contain credentials or operator settings.
        if type(error).__module__.startswith("services.installation_manager"):
            sys.stderr.write(str(error) + "\n")
        elif type(error) is ValueError:
            sys.stderr.write("Offline command parameters or local metadata are invalid\n")
        else:
            sys.stderr.write("Offline operation could not use the required local resources\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
