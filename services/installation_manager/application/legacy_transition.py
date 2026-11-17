"""Read-only, opt-in observation of legacy Compose instances."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from packaging.version import Version
from pydantic import Field

from ..domain.operation_state import InstanceIdentity, ReleasePin
from ..domain.release_manifest import (
    REQUIRED_SERVICES,
    ImageReference,
    Revision,
    VersionText,
    WireModel,
    digest_of,
    strict_json,
)
from ..host_bootstrap import PROJECT, docker, safe_path
from ..infrastructure.maintenance_host import GATE_PARTICIPANTS, PG_TARGET, ComposeMaintenanceHost
from ..infrastructure.release_verification import MAX_MANIFEST_BYTES, TrustPolicy
from ..infrastructure.staging_commands import Deadline, RetryPolicy
from ..infrastructure.staging_compose import (
    COMPOSE_LIMIT,
    _source_service,
    _target_service,
    validate_template,
)
from ..infrastructure.staging_docker import StagingDocker, _compose_value, image_references

LEGACY_SERVICES = REQUIRED_SERVICES - {"migrate"}


class Predecessor(WireModel):
    version: VersionText
    revision: Revision
    images: dict[str, ImageReference]


class LegacyPolicy(WireModel):
    format_version: int = Field(ge=1, le=1)
    predecessors: list[Predecessor] = Field(min_length=1, max_length=32)


def _read(path: Path, limit: int) -> bytes:
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("The selected file is missing or too large")
    return path.read_bytes()


def _topology(value, data: Path) -> dict:
    mounts = []
    for mount in sorted(value.mounts):
        source = Path(mount.source)
        mounts.append({
            "kind": mount.kind,
            "relative_path": (
                str(source.relative_to(data))
                if mount.kind == "bind" and source.is_relative_to(data)
                else None
            ),
            "target": mount.target,
            "read_only": mount.read_only,
        })
    return {
        "bindings": [asdict(item) for item in sorted(value.bindings)],
        "mounts": mounts,
        "networks": sorted(value.networks),
    }


def observe(
    data: Path,
    project: str,
    policy: LegacyPolicy,
    *,
    target=None,
) -> dict:
    """Compare the resolved saved model and actual IDs without running Compose."""
    data = safe_path(data)
    if not PROJECT.fullmatch(project):
        raise ValueError("An explicit Compose project is required")
    compose, env = data / "docker-compose.yaml", data / ".env"
    template = _read(compose, COMPOSE_LIMIT)
    validate_template(template)
    _read(env, 256 * 1024)
    args = (
        "compose", "--project-name", project, "--project-directory", str(data), "--file",
        str(compose), "--env-file", str(env), "--profile", "*",
    )
    model = _compose_value(json.loads(docker(*args, "config", "--format", "json").stdout))
    values = docker(*args, "config", "--environment").stdout.splitlines()
    configured_version = next(
        (row.split("=", 1)[1] for row in values if row.startswith("DVT_VERSION=")), None,
    )
    adapter = StagingDocker(data, Path("/root/.docker"))
    deadline = Deadline(RetryPolicy(), data)
    rows = adapter.containers(project, deadline)
    actual = {}
    instances = {}
    blockers = set()
    drift = set()
    if model["name"] != project:
        blockers.add("compose_project_mismatch")
    for row in rows:
        labels = row["Config"].get("Labels") or {}
        role = labels.get("com.docker.compose.service")
        state = row["State"]
        if (
            labels.get("com.docker.compose.project") != project
            or labels.get("com.docker.compose.oneoff", "").lower() != "false"
            or labels.get("com.docker.compose.project.working_dir") != str(data)
            or labels.get("com.docker.compose.project.config_files") != str(compose)
            or role not in LEGACY_SERVICES | {"migrate", "dvt-ai-mcp"}
        ):
            blockers.add("unconfirmed_compose_scope")
            continue
        if role == "migrate" and state["Status"] == "exited" and state["ExitCode"] == 0:
            continue
        if not state["Running"] or state["Paused"] or state["Restarting"]:
            blockers.add("service_not_running")
            continue
        image = adapter.inspect_image(row["Image"], deadline)
        if image is None:
            blockers.add("image_unavailable")
            continue
        actual.setdefault(role, []).append((row, image))
    if not actual.keys() >= LEGACY_SERVICES:
        blockers.add("missing_source_role")

    matches = [
        approved for approved in policy.predecessors
        if actual.keys() == approved.images.keys() and all(
            approved.images[role] in image_references(image)
            for role, items in actual.items() for _, image in items
        )
    ]
    source = matches[0] if len(matches) == 1 else None
    if source is None:
        blockers.add("unapproved_source_images")

    for role, items in sorted(actual.items()):
        if len(items) != 1 and role != "task-worker":
            blockers.add("unexpected_replicas")
        representative = _source_service(items[0][0])
        instances[role] = {"replicas": len(items), **_topology(representative, data)}
        expected = model["services"].get(role)
        if expected is None:
            drift.add(role)
            continue
        # Only filesystem and Compose identity are used here. The real address and port are
        # taken from the observed manager binding, separately from the saved dotenv.
        identity = _compose_identity(data, project)
        desired = _target_service(role, expected, model, identity)
        count = (expected.get("deploy") or {}).get("replicas", expected.get("scale", 1))
        expected_image = adapter.inspect_image(expected["image"], deadline)
        if count != len(items) or expected_image is None or any(
            (item["Image"] != expected_image["Id"]) or not _same_service(
                _source_service(item), desired
            )
            for item, _ in items
        ):
            drift.add(role)

    if set(model["services"]) - actual.keys() - {"migrate"} - {
        role for role, value in model["services"].items() if value.get("profiles")
    }:
        blockers.add("saved_services_missing")
    if drift:
        blockers.add("saved_model_differs")
    revision = None
    if len(actual.get("postgres", [])) == 1:
        pg_row, _ = actual["postgres"][0]
        pg_mounts = _source_service(pg_row).mounts
        if (
            len(pg_mounts) != 1
            or not any(
                mount.kind == "bind" and not mount.read_only and mount.target == PG_TARGET
                and Path(mount.source).is_relative_to(data)
                for mount in pg_mounts
            )
            or pg_row["HostConfig"].get("PortBindings")
        ):
            blockers.add("unsupported_postgres_layout")
        else:
            try:
                revision = ComposeMaintenanceHost.sql(
                    pg_row["Id"], "SELECT version_num FROM alembic_version",
                )
            except subprocess.SubprocessError:
                blockers.add("database_unavailable")
            else:
                if not revision or not all(c in "0123456789abcdef" for c in revision):
                    revision = None
    if revision is None or source is None or revision != source.revision:
        blockers.add("unconfirmed_source_revision")

    try:
        version_matches = source is not None and Version(configured_version) == Version(
            source.version
        )
    except (TypeError, ValueError):
        version_matches = False
    if not version_matches:
        blockers.add("saved_version_differs")
    guard = all(
        actual.get(role) and all(
            (image.get("Config", {}).get("Labels") or {}).get("tech.denvic.task-admission") == "1"
            for _, image in actual[role]
        )
        for role in GATE_PARTICIPANTS
    )
    if not guard:
        blockers.add("source_has_no_admission_guard")
    route = next((
        route for route in target.database_schema.from_releases
        if source and Version(route.version) == Version(source.version) and route.revision == revision
    ), None) if target is not None else None
    if route is None:
        blockers.add("no_signed_transition")
    return {
        "format_version": 1,
        "project": project,
        "observed_version": source.version if source else None,
        "observed_revision": revision,
        "observed_images": {
            role: ref.rsplit("@", 1)[1] for role, ref in source.images.items()
        } if source else {},
        "services": instances,
        "saved_model_differences": sorted(drift),
        "saved_version_matches": version_matches,
        "signed_route": route.model_dump(mode="json") if route is not None else None,
        "blockers": sorted(blockers),
        "supported_actions": ["review_plan"],
    }


def _compose_identity(data: Path, project: str) -> InstanceIdentity:
    from uuid import UUID

    return InstanceIdentity(UUID(int=1), str(data), project, "127.0.0.1", 1, "http://localhost")


def _same_service(actual, planned) -> bool:
    return (
        actual.mounts == planned.mounts
        and actual.bindings == planned.bindings
        and actual.networks == planned.networks
        and all(actual.database_env.get(key) == value for key, value in planned.database_env.items())
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--predecessors", required=True, type=Path)
    parser.add_argument("--target-manifest", type=Path)
    parser.add_argument("--target-digest")
    parser.add_argument("--target-release")
    parser.add_argument("--trust", type=Path)
    args = parser.parse_args()
    target = None
    try:
        policy = LegacyPolicy.model_validate_json(_read(args.predecessors, 64 * 1024))
        selection = (args.target_manifest, args.target_digest, args.target_release, args.trust)
        if any(selection):
            if not all(selection):
                raise ValueError("A complete pinned target selection is required")
            content = _read(args.target_manifest, MAX_MANIFEST_BYTES)
            pin = ReleasePin(args.target_release, args.target_digest)
            if digest_of(content) != pin.manifest_digest:
                raise ValueError("The target manifest does not match its pin")
            trust = TrustPolicy.from_document(strict_json(_read(args.trust, 64 * 1024)))
            target = trust.verify(content, pin)
        report = observe(args.dir, args.project, policy, target=target)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.SubprocessError):
        sys.stderr.write("Could not establish the legacy Compose observation\n")
        return 1
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
