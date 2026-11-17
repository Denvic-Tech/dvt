"""Validate the signed Compose model and compare it with the local Docker project."""

from __future__ import annotations

import ipaddress
import os
import posixpath
from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml

from ..domain.operation_state import (
    FailureReason,
    InstanceIdentity,
    OperationRequest,
    ReleasePin,
    _public_origin,
)
from ..domain.release_manifest import (
    REQUIRED_SERVICES,
    ImageReference,
    PlatformRelease,
    Revision,
    StagingError,
    VersionText,
    WireModel,
)
from ..domain.services import render_bool
from .operator_wiring import operator_binds
from .staging_commands import Deadline
from .staging_docker import StagingDocker, image_references
from .staging_host import check_free_port, incompatible

COMPOSE_LIMIT = 4 * 1024 * 1024
DATABASE_ENV = {
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "PGDATA",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "VALKEY_HOST",
    "VALKEY_PORT",
    "VALKEY_PASSWORD",
    "VALKEY_DB",
}
AI_SECRET = "DVT_AI_MCP_INTERNAL_SECRET"


class ObservedRelease(WireModel):
    """Facts from version/schema observation and the expected complete running source image set."""

    version: VersionText
    revision: Revision
    pin: ReleasePin | None
    images: dict[str, ImageReference]


@dataclass(frozen=True, order=True)
class Binding:
    address: str
    port: int
    target: int
    protocol: Literal["tcp", "udp"]


@dataclass(frozen=True, order=True)
class Mount:
    kind: Literal["bind", "volume"]
    source: str
    target: str
    read_only: bool


@dataclass(frozen=True)
class Service:
    image: str
    mounts: frozenset[Mount]
    bindings: frozenset[Binding]
    networks: frozenset[str]
    database_env: dict[str, str | None] = field(repr=False)


@dataclass(frozen=True)
class ComposePlan:
    additions: tuple[str, ...]
    recreate: tuple[str, ...]
    retire: tuple[str, ...]
    image_references: dict[str, str]
    source_images: dict[str, str]
    persistent_paths: set[Path]


def compose_error(problem: str) -> StagingError:
    return StagingError(
        FailureReason.COMPOSE,
        problem,
        "Check the signed Compose file, selected settings and existing Docker project",
    )


def effective_config(
    values: dict[str, str],
    identity: InstanceIdentity,
    request: OperationRequest,
    release_version: str,
    desired_workers: int,
) -> tuple[dict[str, str], tuple[str, ...]]:
    environment = dict(values)
    public_origins = [
        origin.strip() for origin in values.get("DVT_PUBLIC_URL", "").split(";") if origin.strip()
    ]
    try:
        public_origins = [_public_origin(origin) for origin in public_origins] or [
            identity.public_url
        ]
    except ValueError:
        raise compose_error(
            "The selected configuration contains an invalid public origin"
        ) from None
    if public_origins[0] != identity.public_url:
        raise compose_error("The saved primary public origin conflicts with installation identity")
    raw_enabled = environment.get("DVT_AI_MCP_ENABLED", "false").lower()
    if raw_enabled not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        raise compose_error("Invalid saved AI MCP setting")
    saved_enabled = raw_enabled in ("true", "1", "yes", "on")
    saved_profiles = set(
        filter(None, map(str.strip, environment.pop("COMPOSE_PROFILES", "").split(",")))
    )
    if saved_profiles - {"ai-mcp"}:
        raise compose_error("The selected configuration has unsupported Compose profiles")
    if saved_enabled != ("ai-mcp" in saved_profiles) and "DVT_AI_MCP_ENABLED" in values:
        raise compose_error("Saved AI MCP settings disagree with the saved Compose profiles")
    enabled = (
        request.ai_mcp_enabled
        if request.ai_mcp_enabled is not None
        else saved_enabled or bool(saved_profiles)
    )
    try:
        workers = request.task_workers_count or int(environment.get("DVT_TASK_WORKERS_COUNT", "1"))
        app_port = request.app_port or int(environment.get("DVT_EXTERNAL_PORT", "80"))
        if not 1 <= workers <= desired_workers or not 1 <= app_port <= 65535:
            raise ValueError
    except ValueError:
        raise compose_error(
            "The selected port or worker count is outside the environment profile"
        ) from None
    if enabled and not environment.get(AI_SECRET, "").strip():
        raise compose_error("The enabled AI MCP profile requires a saved internal secret")
    environment.update(
        {
            "DVT_LIB_DIR": identity.data_dir,
            "DVT_PUBLIC_URL": ";".join(public_origins),
            "DVT_VERSION": release_version,
            "DVT_INSTALLATION_MANAGER_EXTERNAL_PORT": str(identity.manager_port),
            "DVT_INSTALLATION_MANAGER_BIND_ADDRESS": identity.manager_address,
            "DVT_INSTALLATION_MANAGER_DATA_TARGET": identity.data_dir,
            "DVT_AI_MCP_ENABLED": render_bool(enabled),
            "DVT_EXTERNAL_PORT": str(app_port),
            "DVT_TASK_WORKERS_COUNT": str(workers),
        }
    )
    profiles = ("ai-mcp",) if enabled else ()
    environment.setdefault("DVT_NETWORK_NAME", f"{identity.compose_project}_dvt-net")
    environment.setdefault("DVT_NETWORK_EXTERNAL", "false")
    environment["COMPOSE_PROFILES"] = ",".join(profiles)
    return environment, profiles


def validate_template(content: bytes) -> None:
    try:
        template = yaml.safe_load(content)
        if (
            set(template)
            - {"services", "networks", "volumes", "version", "name"}
            - {key for key in template if isinstance(key, str) and key.startswith("x-")}
        ):
            raise ValueError
        for service in template["services"].values():
            if {
                "build",
                "extends",
                "env_file",
                "label_file",
                "configs",
                "secrets",
                "provider",
                "develop",
                "post_start",
                "pre_stop",
                "volumes_from",
                "network_mode",
                "external_links",
                "devices",
                "credential_spec",
                "models",
            } & service.keys():
                raise ValueError
    except (ValueError, TypeError, AttributeError, KeyError, yaml.YAMLError, RecursionError):
        raise compose_error(
            "Compose must be self-contained and use supported service options"
        ) from None


def check_model(
    model: dict,
    identity: InstanceIdentity,
    release: PlatformRelease,
    environment: dict[str, str],
    active: bool,
) -> None:
    if (
        model.get("name") != identity.compose_project
        or not isinstance(model.get("services"), dict)
        or not model["services"].keys() >= REQUIRED_SERVICES
    ):
        raise compose_error(
            "The resolved model lacks the confirmed project name or mandatory services"
        )
    expected = {name: image.reference for name, image in release.images.items()}
    actual = {name: value.get("image") for name, value in model["services"].items()}
    if (not active and actual != expected) or (
        active and any(expected.get(name) != ref for name, ref in actual.items())
    ):
        raise compose_error("Compose images do not match the signed platform-specific image set")

    gateway = model["services"]["gateway"].get("environment") or {}
    mcp = model["services"].get("dvt-ai-mcp")
    if active:
        worker = model["services"]["task-worker"]
        replicas = (worker.get("deploy") or {}).get("replicas", worker.get("scale", 1))
        if replicas != int(environment["DVT_TASK_WORKERS_COUNT"]):
            raise compose_error(
                "The resolved worker replica count disagrees with the selected configuration"
            )
        enabled = environment.get("DVT_AI_MCP_ENABLED") == "true"
        if enabled != (mcp is not None):
            raise compose_error(
                "The resolved AI MCP service set disagrees with the requested profile"
            )
        if enabled:
            saved = environment[AI_SECRET]
            if (
                str(gateway.get("DVT_AI_MCP_ENABLED", "")).lower() != "true"
                or gateway.get(AI_SECRET) != saved
                or (mcp.get("environment") or {}).get(AI_SECRET) != saved
            ):
                raise compose_error(
                    "The enabled Gateway and AI MCP have inconsistent configuration"
                )
        elif str(gateway.get("DVT_AI_MCP_ENABLED", "false")).lower() not in ("", "false", "0"):
            raise compose_error("Gateway would enable AI MCP while its Compose profile is disabled")


def _bindings(values: list[dict]) -> frozenset[Binding]:
    result = set()
    for value in values:
        if value.get("protocol", "tcp") not in ("tcp", "udp"):
            raise compose_error("Compose binding uses an unsupported transport")
        try:
            address = ipaddress.ip_address(value.get("host_ip") or "0.0.0.0").compressed
            port, target = int(value["published"]), int(value["target"])
            if not 1 <= port <= 65535 or not 1 <= target <= 65535:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise compose_error("Compose must publish explicitly selected host ports") from None
        result.add(Binding(address, port, target, value.get("protocol", "tcp")))
    return frozenset(result)


def _check_binding_collisions(services: dict[str, Service]) -> None:
    bindings = [binding for service in services.values() for binding in service.bindings]
    for left, right in combinations(bindings, 2):
        if (left.port, left.protocol) != (right.port, right.protocol):
            continue
        if (
            left.address == right.address
            or "::" in (left.address, right.address)
            or (
                "0.0.0.0" in (left.address, right.address)
                and not any(":" in binding.address for binding in (left, right))
            )
        ):
            raise compose_error("Two Compose bindings compete for the same host port")


def _target_service(
    name: str,
    value: dict,
    model: dict,
    identity: InstanceIdentity,
) -> Service:
    mounts: set[Mount] = set()
    volume_definitions = model.get("volumes") or {}
    for mount in value.get("volumes") or []:
        kind, source = mount.get("type"), mount.get("source")
        if kind == "bind" and isinstance(source, str):
            if source == "/var/run/docker.sock" and name == "installation_manager":
                pass
            elif (
                not (source == identity.data_dir or source.startswith(identity.data_dir + "/"))
                or posixpath.normpath(source) != source
                or source == identity.data_dir + "/.installation-state"
                or source.startswith(identity.data_dir + "/.installation-state/")
                or (os.name == "posix" and Path(source).resolve(strict=False) != Path(source))
            ):
                raise compose_error(
                    "A Compose bind mount is outside the canonical DVT data directory"
                )
            if (mount.get("bind") or {}).get("propagation", "rprivate") != "rprivate":
                raise compose_error("A Compose bind mount uses unsupported propagation")
        elif kind == "volume" and source in volume_definitions:
            source = volume_definitions[source]["name"]
        else:
            raise compose_error("Compose must use a supported explicit bind or named volume")
        mounts.add(Mount(kind, source, mount["target"], bool(mount.get("read_only"))))
    networks = frozenset(model["networks"][key]["name"] for key in value.get("networks") or {})
    return Service(
        value["image"],
        frozenset(mounts),
        _bindings(value.get("ports") or []),
        networks,
        {key: val for key, val in (value.get("environment") or {}).items() if key in DATABASE_ENV},
    )


def _source_service(container: dict) -> Service:
    ports = []
    for key, bindings in (container["HostConfig"].get("PortBindings") or {}).items():
        target, _, protocol = key.partition("/")
        for value in bindings or []:
            ports.append(
                {
                    "host_ip": value["HostIp"],
                    "published": value["HostPort"],
                    "target": target,
                    "protocol": protocol,
                }
            )
    env = dict(line.split("=", 1) for line in container["Config"]["Env"] or [] if "=" in line)
    return Service(
        container["Image"],
        frozenset(
            Mount(
                mount["Type"],
                mount["Name"] if mount["Type"] == "volume" else mount["Source"],
                mount["Destination"],
                not mount["RW"],
            )
            for mount in container.get("Mounts") or []
        ),
        _bindings(ports),
        frozenset((container["NetworkSettings"].get("Networks") or {}).keys()),
        {key: val for key, val in env.items() if key in DATABASE_ENV},
    )


def _approve_networks(
    model: dict,
    docker: StagingDocker,
    deadline: Deadline,
) -> None:
    for network in (model.get("networks") or {}).values():
        actual = docker.network(network["name"], deadline)
        if actual is None:
            if network.get("external"):
                raise compose_error("A required external Compose network does not exist")
            continue
        if network.get("external"):
            if actual.get("Scope") != "local" or actual.get("Driver") != "bridge":
                raise incompatible(
                    "The existing external network is outside the supported local bridge profile"
                )
            continue
        if (
            (actual.get("Labels") or {}).get("com.docker.compose.project") != model["name"]
            or actual.get("Driver") != network.get("driver", "bridge")
            or actual.get("Internal") != network.get("internal", False)
            or (actual.get("Options") or {}) != (network.get("driver_opts") or {})
            or network.get("ipam")
            or bool(actual.get("EnableIPv6")) != bool(network.get("enable_ipv6"))
        ):
            raise incompatible(
                "The existing Compose network would change ownership or network settings"
            )


def _persistent_paths(
    volumes: dict,
    project: str,
    source: dict[str, list[Service]],
    target: dict[str, Service],
    docker: StagingDocker,
    deadline: Deadline,
) -> set[Path]:
    by_name = {volume["name"]: (key, volume) for key, volume in volumes.items()}
    paths: set[Path] = set()
    for name, values in source.items():
        if name == "installation_manager":
            continue
        for mount in values[0].mounts:
            if mount.kind == "bind" and mount.source != "/var/run/docker.sock":
                paths.add(Path(mount.source))
    for service in target.values():
        for mount in service.mounts:
            if mount.kind != "volume":
                continue
            key, wanted = by_name[mount.source]
            actual = docker.volume(mount.source, deadline)
            if actual is None:
                if wanted.get("external") or source:
                    raise incompatible("An expected named volume does not exist")
                continue
            labels = actual.get("Labels") or {}
            if (
                actual.get("Driver") != "local"
                or wanted.get("driver", "local") != "local"
                or wanted.get("driver_opts")
                or actual.get("Options")
                or (
                    not wanted.get("external")
                    and (
                        labels.get("com.docker.compose.project") != project
                        or labels.get("com.docker.compose.volume") != key
                    )
                )
            ):
                raise incompatible(
                    "The existing named volume is outside the supported local storage profile"
                )
            if not source:
                raise incompatible("Initial installation would reuse an existing named volume")
            paths.add(Path(actual["Mountpoint"]))
    # Avoid charging the same files twice when a parent directory is mounted as well.
    return {path for path in paths if not any(parent in paths for parent in path.parents)}


def _check_container_names(
    services: dict, project: str, docker: StagingDocker, deadline: Deadline,
) -> None:
    names = {}
    for role, service in services.items():
        name = service.get("container_name")
        if name is None:
            continue
        if name in names:
            raise compose_error(f"Compose uses container name {name} for multiple active services")
        names[name] = role
    if not names:
        return
    for container in docker.containers_named(list(names), deadline):
        name = container["Name"].removeprefix("/")
        role = names.get(name)
        if role is None:
            continue
        labels = container["Config"].get("Labels") or {}
        if (
            labels.get("com.docker.compose.project") != project
            or labels.get("com.docker.compose.service") != role
            or labels.get("com.docker.compose.oneoff", "").lower() == "true"
        ):
            raise compose_error(
                f"Container name {name} for service {role} is occupied outside the confirmed role"
            )


def compare_project(
    model: dict,
    identity: InstanceIdentity,
    config: dict[str, str],
    docker: StagingDocker,
    observed: ObservedRelease | None,
    deadline: Deadline,
    *,
    bootstrap_image: str | None = None,
    require_bootstrap_manager: bool = False,
) -> ComposePlan:
    _check_container_names(model["services"], identity.compose_project, docker, deadline)
    target = {
        name: _target_service(name, value, model, identity)
        for name, value in model["services"].items()
    }
    _check_binding_collisions(target)
    manager = target["installation_manager"]
    if len(manager.bindings) != 1 or not any(
        binding.address == identity.manager_address
        and binding.port == identity.manager_port
        and binding.protocol == "tcp"
        for binding in manager.bindings
    ):
        raise compose_error("Compose manager bindings disagree with saved installation identity")
    if "proxy" not in target or not any(
        binding.port == int(config["DVT_EXTERNAL_PORT"]) and binding.protocol == "tcp"
        for binding in target["proxy"].bindings
    ):
        raise compose_error("Compose proxy bindings disagree with the selected application port")
    for name, destination in (("postgres", "/var/lib/postgresql/data"), ("valkey", "/data")):
        persistent = [
            mount
            for mount in target[name].mounts
            if mount.target == destination and not mount.read_only
        ]
        if len(persistent) != 1:
            raise compose_error(
                "Compose database and Valkey require explicit persistent data mounts"
            )
        if observed is None and persistent[0].kind == "bind":
            path = Path(persistent[0].source)
            if path.is_dir() and next(path.iterdir(), None) is not None:
                raise incompatible(
                    "Initial installation would reuse an existing database or Valkey data directory"
                )
    if target["migrate"].bindings:
        raise compose_error("The one-time migration service cannot publish ports")

    source: dict[str, list[Service]] = {}
    source_references: dict[str, str] = {}
    for container in docker.containers(identity.compose_project, deadline):
        labels = container["Config"].get("Labels") or {}
        name = labels.get("com.docker.compose.service")
        if (
            labels.get("com.docker.compose.project") != identity.compose_project
            or not name
            or labels.get("com.docker.compose.oneoff", "").lower() == "true"
        ):
            raise incompatible(
                "The current project contains a conflicting one-off or unidentified container"
            )
        if name == "migrate" and observed is not None and not container["State"]["Running"]:
            continue
        expected_image = (
            observed.images.get(name)
            if observed is not None
            else bootstrap_image
            if name == "installation_manager" and name not in source
            else None
        )
        if not expected_image or not container["State"]["Running"]:
            raise incompatible(
                "Running project contents differ from the independently established source"
            )
        image = docker.inspect_image(container["Image"], deadline)
        if image is None or expected_image not in image_references(image):
            raise incompatible(
                "A running service image differs from the independently established source"
            )
        source_references[name] = expected_image
        source.setdefault(name, []).append(_source_service(container))
    if observed is not None and set(source) != set(observed.images):
        raise incompatible("The expected running service set is incomplete or changed")
    if require_bootstrap_manager and "installation_manager" not in source_references:
        raise StagingError(
            FailureReason.MANAGER_UNAVAILABLE,
            "The confirmed bootstrap manager is not running",
            "Restore the approved bootstrap manager and continue the same operation",
            retryable=True,
        )

    for name, services in source.items():
        if name not in target:
            if name in {"postgres", "valkey"} or any(
                service.mounts or service.bindings for service in services
            ):
                raise incompatible("The candidate removes a persistent service or published port")
            continue
        planned = target[name]
        for index, observed_service in enumerate(services):
            current = observed_service
            if name == "gateway":
                injected = frozenset(
                    Mount("bind", source, path, True)
                    for path, source in operator_binds(identity.data_dir).items()
                )
                if injected <= current.mounts:
                    # Ignore only the two protected read-only binds and the manager network.
                    current = replace(
                        current, mounts=current.mounts - injected,
                        networks=current.networks - (manager.networks - planned.networks),
                    )
                    # Staging budgets must also use the normalized persistent mounts.
                    services[index] = current
            if (
                current.mounts != planned.mounts
                or current.bindings != planned.bindings
                or current.networks != planned.networks
                or any(
                    key not in current.database_env or current.database_env[key] != val
                    for key, val in planned.database_env.items()
                )
                or any(
                    key not in planned.database_env
                    for key in current.database_env
                    if key != "PGDATA"
                )
            ):
                raise incompatible(
                    "Candidate changes data mounts, ports, networks or database credentials for a running service"
                )
        if name in {"postgres", "valkey"} and planned.image != source_references[name]:
            raise incompatible("This profile does not support a PostgreSQL or Valkey image change")

    for name, service in target.items():
        if name not in source:
            for binding in service.bindings:
                check_free_port(binding.address, binding.port, binding.protocol)
            for mount in service.mounts:
                if mount.kind == "bind" and mount.source != "/var/run/docker.sock":
                    path = PurePosixPath(mount.source)
                    if (
                        observed is not None
                        and path != PurePosixPath(identity.data_dir)
                        and not Path(path).is_dir()
                    ):
                        raise incompatible(
                            "A newly enabled service would create an unexpected data directory"
                        )
    _approve_networks(model, docker, deadline)
    persistent_paths = _persistent_paths(
        model.get("volumes") or {},
        identity.compose_project,
        source if observed is not None else {},
        target,
        docker,
        deadline,
    )
    return ComposePlan(
        tuple(sorted(target.keys() - source.keys())),
        tuple(sorted(target.keys() & source.keys())),
        tuple(sorted(source.keys() - target.keys())),
        {name: service.image for name, service in target.items()},
        source_references,
        persistent_paths,
    )
