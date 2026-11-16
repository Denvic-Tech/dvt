"""Read-only Docker observations and pinned image pulls on the executor host."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..domain.operation_state import FailureReason
from ..domain.release_manifest import StagingError
from .staging_commands import Deadline, Output, run_quietly
from .staging_downloads import classify_io_error


def read_docker_json(content: bytes, description: str) -> object:
    try:
        return json.loads(content)
    except (ValueError, RecursionError):
        raise StagingError(
            FailureReason.COMPOSE,
            f"Could not read the Docker {description}",
            "Check the supported Docker Engine and Compose versions",
        ) from None


def _compose_value(value):
    # "config" escapes literal dollar signs so its output can be parsed again.
    # Staging compares the effective values with actual Docker observations instead.
    if isinstance(value, str):
        return value.replace("$$", "$")
    if isinstance(value, list):
        return [_compose_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _compose_value(item) for key, item in value.items()}
    return value


def _canonical_reference(name: str) -> str:
    registry, _, _ = name.partition("/")
    if "/" not in name:
        return f"docker.io/library/{name}"
    if "." not in registry and ":" not in registry:
        return f"docker.io/{name}"
    return (
        name.replace("index.docker.io/", "docker.io/", 1) if registry == "index.docker.io" else name
    )


def image_references(image: dict) -> set[str]:
    return {_canonical_reference(name) for name in image.get("RepoDigests") or []}


@dataclass(frozen=True)
class StagingDocker:
    directory: Path
    config_dir: Path
    endpoint: str = "unix:///var/run/docker.sock"
    registry_hosts: frozenset[str] = frozenset({"docker.io"})

    def __post_init__(self) -> None:
        if not self.endpoint.startswith("unix:///") or not self.config_dir.is_absolute():
            raise ValueError(
                "Staging requires an explicit local Docker socket and config directory"
            )

    def _run(
        self,
        command: list[str],
        deadline: Deadline,
        *,
        reason: FailureReason = FailureReason.COMPOSE,
        env: dict[str, str] | None = None,
    ) -> Output:
        return run_quietly(
            ["docker", "--config", str(self.config_dir), "--host", self.endpoint, *command],
            deadline,
            reason,
            cwd=self.directory,
            env=env,
        )

    def _checked(self, command: list[str], deadline: Deadline, description: str) -> bytes:
        result = self._run(command, deadline)
        if result.code:
            raise StagingError(
                FailureReason.COMPOSE,
                f"Docker could not {description}",
                "Check the local Docker daemon and the existing project state",
            )
        return result.stdout

    def info(self, deadline: Deadline) -> dict:
        content = self._checked(
            ["info", "--format", "{{json .}}"], deadline, "read host capabilities"
        )
        return read_docker_json(content, "system information")

    def compose_version(self, deadline: Deadline) -> str:
        return (
            self._checked(
                ["compose", "version", "--short"],
                deadline,
                "read the Compose version",
            )
            .decode()
            .strip()
            .removeprefix("v")
        )

    def config(
        self,
        path: Path,
        project: str,
        profiles: tuple[str, ...],
        env: dict[str, str],
        deadline: Deadline,
    ) -> dict:
        args = [
            "compose",
            "--project-directory",
            str(path.parent),
            "--project-name",
            project,
            "--file",
            str(path),
            "--env-file",
            "/dev/null",
        ]
        for profile in profiles:
            args.extend(["--profile", profile])
        result = self._run(
            [*args, "config", "--format", "json", "--no-env-resolution"], deadline, env=env
        )
        if result.code or b"variable is not set" in result.stderr.lower():
            raise StagingError(
                FailureReason.COMPOSE,
                "Compose configuration could not be resolved",
                "Check the signed template and saved configuration for required values",
            )
        return _compose_value(read_docker_json(result.stdout, "Compose model"))

    def containers(self, project: str, deadline: Deadline) -> list[dict]:
        ids = (
            self._checked(
                [
                    "ps",
                    "--all",
                    "--quiet",
                    "--no-trunc",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                ],
                deadline,
                "list containers in the confirmed project",
            )
            .decode()
            .split()
        )
        if not ids:
            return []
        result = self._checked(
            ["container", "inspect", *ids], deadline, "inspect the confirmed project"
        )
        return read_docker_json(result, "container inspection")

    def inspect_image(self, reference: str, deadline: Deadline) -> dict | None:
        result = self._run(["image", "inspect", reference], deadline)
        if result.code:
            if b"no such image" in result.stderr.lower():
                return None
            raise StagingError(
                FailureReason.COMPOSE,
                "Docker could not inspect a local image",
                "Check daemon availability and image store integrity",
            )
        data = read_docker_json(result.stdout, "image inspection")
        return data[0]

    def local_image(self, reference: str, platform: str, deadline: Deadline) -> bool:
        info = self.inspect_image(reference, deadline)
        if info is None:
            return False
        descriptor = info.get("Descriptor") or {}
        if "index" in descriptor.get("mediaType", "") or "manifest.list" in descriptor.get(
            "mediaType", ""
        ):
            raise StagingError(
                FailureReason.INVALID_PACKAGE,
                "The image pin points at an index instead of a platform manifest",
                "Publish the selected platform manifest digest",
            )
        if (
            reference not in image_references(info)
            or f"{info.get('Os')}/{info.get('Architecture')}" != platform
        ):
            raise StagingError(
                FailureReason.INVALID_PACKAGE,
                "The local image does not match the pinned digest and platform",
                "Check the integrity of the local image store and the expected artifact",
            )
        return True

    def check_registries(self, references: set[str], info: dict) -> None:
        hosts = {reference.partition("/")[0] for reference in references}
        config = info.get("RegistryConfig") or {}
        insecure_hosts = {
            host
            for host, value in (config.get("IndexConfigs") or {}).items()
            if not value.get("Secure")
        }
        insecure_ranges = set(config.get("InsecureRegistryCIDRs") or ()) - {
            "127.0.0.0/8",
            "::1/128",
        }
        if (
            not hosts <= self.registry_hosts
            or hosts & insecure_hosts
            or insecure_ranges
            or any(
                host.partition(":")[0] in {"localhost", "0.0.0.0"} or host.startswith("127.")
                for host in hosts
            )
        ):
            raise StagingError(
                FailureReason.TLS,
                "Registry settings do not satisfy the pinned HTTPS policy",
                "Check trusted registry hosts and disable insecure registry settings for this executor",
            )

    def pull(self, reference: str, platform: str, deadline: Deadline) -> None:
        reason = FailureReason.REGISTRY_UNAVAILABLE

        def download() -> None:
            result = self._run(
                ["image", "pull", "--quiet", "--platform", platform, reference],
                deadline,
                reason=reason,
            )
            if result.code:
                raise classify_io_error(reason, result.stderr + result.stdout)
            if not self.local_image(reference, platform, deadline):
                raise StagingError(
                    FailureReason.INVALID_PACKAGE,
                    "Docker did not store the pinned platform image",
                    "Check image-store integrity and Registry delivery",
                )

        deadline.retry(download, reason)

    def network(self, name: str, deadline: Deadline) -> dict | None:
        result = self._run(["network", "inspect", name], deadline)
        if result.code:
            if b"not found" in result.stderr.lower() or b"no such network" in result.stderr.lower():
                return None
            raise StagingError(
                FailureReason.COMPOSE,
                "Docker could not inspect a project network",
                "Check Docker networking",
            )
        return read_docker_json(result.stdout, "network inspection")[0]

    def volume(self, name: str, deadline: Deadline) -> dict | None:
        result = self._run(["volume", "inspect", name], deadline)
        if result.code:
            if b"no such volume" in result.stderr.lower():
                return None
            raise StagingError(
                FailureReason.COMPOSE,
                "Docker could not inspect a project volume",
                "Check Docker volumes",
            )
        return read_docker_json(result.stdout, "volume inspection")[0]
