"""Run once when an old DVT installer or updater starts the compatibility Compose."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .domain.release_manifest import canonical_json
from .host_bootstrap import (
    CONTROL,
    HOST_OS_RELEASE,
    PROJECT,
    STATE,
    atomic_write,
    check_image,
    docker,
    mount,
)
from .infrastructure.staging_artifacts import read_artifact

LABEL = "tech.denvic.legacy-bridge"
MARKER = Path("installation/legacy-entry.json")
PACKAGE = Path(__file__).with_name("legacy_bridge")
LEGACY_MOUNT = Path("/dvt-lib")
LEGACY_COMPOSE = str(LEGACY_MOUNT / "docker-compose.yaml")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
CONTAINER_ID = re.compile(r"[0-9a-f]{12,64}")
JOB_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}")
READ_JOB = (
    "import sys,urllib.request;"
    "sys.stdout.buffer.write(urllib.request.urlopen("
    "'http://127.0.0.1:8000/api/jobs/current/summary',timeout=3).read(16385))"
)


def _inspect(*ids: str) -> list[dict]:
    return json.loads(docker("container", "inspect", *ids, timeout=15).stdout)


def _labels(container: dict) -> dict:
    return container["Config"]["Labels"] or {}


def _legacy_manager(project: str, data: Path) -> str:
    ids = docker(
        "container", "ls", "--quiet", "--no-trunc",
        "--filter", f"label=com.docker.compose.project={project}",
        "--filter", "label=com.docker.compose.service=installation_manager",
        timeout=15,
    ).stdout.split()
    if len(ids) != 1 or not CONTAINER_ID.fullmatch(ids[0]):
        raise ValueError("The old installation manager is not uniquely identifiable")
    [container] = _inspect(ids[0])
    if not _is_legacy_manager(container, project, data):
        raise ValueError("The old manager does not belong to this installation")
    return ids[0]


def _is_legacy_manager(container: dict, project: str, data: Path) -> bool:
    labels = _labels(container)
    return (
        labels.get("com.docker.compose.project") == project
        and labels.get("com.docker.compose.service") == "installation_manager"
        and labels.get("com.docker.compose.oneoff", "").lower() == "false"
        and LABEL not in labels
        and any(
            item["Type"] == "bind" and item["Source"] == str(data)
            and item["Destination"] == str(LEGACY_MOUNT) and item["RW"]
            for item in container["Mounts"]
        )
        and any(
            item["Type"] == "bind" and item["Source"] == "/var/run/docker.sock"
            and item["Destination"] == "/var/run/docker.sock"
            for item in container["Mounts"]
        )
    )


def _job(manager: str, requested: str, started_container: datetime, *, timeout: int = 120) -> dict:
    deadline = time.monotonic() + timeout
    job_id = None
    while time.monotonic() < deadline:
        reply = docker(
            "exec", manager, "python3", "-c", READ_JOB, timeout=5, check=False,
        )
        if not reply.returncode:
            job = json.loads(reply.stdout)
            started = datetime.fromisoformat(job["started_at"])
            if (
                len(reply.stdout) > 16384 or not JOB_ID.fullmatch(job["id"])
                or job["kind"] not in {"install", "update"}
                or job["version"] != requested
                or started > started_container
                or (job_id is not None and job_id != job["id"])
            ):
                raise ValueError("The old update or installation could not be correlated")
            job_id = job["id"]
            if job["state"] == "succeeded":
                return job
            if job["state"] != "running":
                raise ValueError("The old Compose command failed before handoff")
        time.sleep(1)
    raise ValueError("Timed out waiting for the old Compose command to finish")


def _handoff_identity(marker: dict) -> tuple[str, str]:
    identity = hashlib.sha256(
        f'{marker["project"]}/{marker["job_id"]}'.encode()
    ).hexdigest()[:24]
    return f"dvt-legacy-handoff-{identity}", identity


def _handoff_arguments(data: Path, job_id: str, image: str) -> list[str]:
    return ["-m", "services.installation_manager.legacy_entry", "--handoff", str(data), job_id, image]


def _start_handoff(data: Path, image: str, marker: dict) -> None:
    name, identity = _handoff_identity(marker)
    existing = docker("container", "inspect", name, check=False, timeout=15)
    if not existing.returncode:
        [container] = json.loads(existing.stdout)
        if (
            _labels(container).get(f"{LABEL}.handoff") != identity
            or container["Config"]["Image"] != image
        ):
            raise ValueError("The legacy handoff container name is already in use")
        if container["State"]["Status"] == "exited" and container["State"]["ExitCode"]:
            docker("container", "start", name, timeout=15)
        return
    docker(
        "run", "--detach", "--name", name, "--pull=never", "--network=host",
        "--restart=unless-stopped", "--platform", "linux/amd64",
        "--label", f"{LABEL}.handoff={identity}",
        "--mount", mount(str(data)),
        "--mount", mount("/var/run/docker.sock"),
        "--mount", mount("/etc/os-release", str(HOST_OS_RELEASE), readonly=True),
        "--entrypoint", "python3", image,
        *_handoff_arguments(data, marker["job_id"], image),
        timeout=30,
    )


def _selection(marker: dict) -> None:
    if (
        marker["format_version"] != 1 or not PROJECT.fullmatch(marker["project"])
        or not JOB_ID.fullmatch(marker["job_id"])
        or marker["kind"] not in {"update", "install"}
        or not DIGEST.fullmatch(marker["manifest_digest"])
        or not VERSION.fullmatch(marker["target_version"])
        or (
            marker["requested_version"] != "latest"
            and marker["requested_version"] != marker["target_version"]
        )
    ):
        raise ValueError("Invalid pinned legacy handoff")


def bootstrap() -> None:
    hostname = os.environ["HOSTNAME"]
    if not CONTAINER_ID.fullmatch(hostname):
        raise ValueError("Expected the private compatibility Compose role")
    [container] = _inspect(hostname)
    labels = _labels(container)
    project = labels["com.docker.compose.project"]
    image = os.environ["DVT_LEGACY_BRIDGE_IMAGE"]
    image_id = check_image(image)
    if (
        labels.get(LABEL) != "1"
        or labels.get("com.docker.compose.service") != "orchestrator"
        or labels.get("com.docker.compose.project.config_files") != LEGACY_COMPOSE
        or container["Config"]["Image"] != image
        or container["Image"] != image_id
        or not PROJECT.fullmatch(project)
    ):
        raise ValueError("Expected the pinned compatibility Compose role")
    [storage] = (item for item in container["Mounts"] if item["Destination"] == str(LEGACY_MOUNT))
    data = Path(storage["Source"])
    if (
        storage["Type"] != "bind" or not storage["RW"]
        or str(data) != os.environ["DVT_LEGACY_DATA"]
        or not re.fullmatch(r"/[a-zA-Z0-9_./-]+", str(data)) or ".." in data.parts
    ):
        raise ValueError("The compatibility Compose data mount differs")

    requested = os.environ["DVT_LEGACY_REQUESTED_VERSION"]
    job = _job(
        _legacy_manager(project, data), requested,
        datetime.fromisoformat(container["State"]["StartedAt"]),
    )
    marker = {
        "format_version": 1, "job_id": job["id"], "kind": job["kind"],
        "started_at": job["started_at"], "requested_version": requested,
        "target_version": os.environ["DVT_LEGACY_TARGET_VERSION"],
        "manifest_digest": os.environ["DVT_LEGACY_TARGET_DIGEST"], "project": project,
    }
    _selection(marker)
    if marker["kind"] == "update":
        from .legacy_entry_recovery import capture_backups

        marker["backups"] = capture_backups(LEGACY_MOUNT)
        marker["managed_paths_absent"] = not any(
            os.path.lexists(LEGACY_MOUNT / name) for name in (CONTROL, STATE)
        )
    path = LEGACY_MOUNT / MARKER
    if path.parent.is_symlink() or path.is_symlink() or not path.parent.is_dir():
        raise ValueError("The legacy installation marker path is invalid")
    atomic_write(path, canonical_json(marker))
    _start_handoff(data, image, marker)


def handoff(data: Path, job_id: str, image: str) -> None:
    from .host_bootstrap import safe_path

    data = safe_path(data)
    path = safe_path(data / MARKER)
    content = read_artifact(path, 4096)
    if content is None:
        raise ValueError("The legacy handoff marker is missing")
    marker = json.loads(content)
    _selection(marker)
    if marker["job_id"] != job_id:
        raise ValueError("A newer legacy job has taken ownership of the handoff")
    name, identity = _handoff_identity(marker)
    [detached] = _inspect(name)
    if (
        detached["Name"] != f"/{name}"
        or detached["HostConfig"]["NetworkMode"] != "host"
        or _labels(detached).get(f"{LABEL}.handoff") != identity
        or detached["Config"]["Image"] != image
        or detached["Config"]["Cmd"] != _handoff_arguments(data, job_id, image)
    ):
        raise ValueError("The detached legacy handoff container differs from the pinned image")

    from .legacy_entry_supervisor import run

    phase = run(data, marker, image, PACKAGE)
    docker("update", "--restart=no", detached["Id"], timeout=15)
    sys.stdout.write(f"DVT legacy handoff: {phase}\n")


def main() -> int:
    try:
        if len(sys.argv) == 1:
            bootstrap()
        elif len(sys.argv) == 5 and sys.argv[1] == "--handoff":
            handoff(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
        else:
            raise ValueError("Invalid legacy bridge invocation")
    except (OSError, ValueError, AttributeError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Child commands own detailed diagnosis. Old dotenv/registry values never go to logs.
        sys.stderr.write(f"DVT legacy handoff stopped ({type(error).__name__})\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
