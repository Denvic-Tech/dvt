"""Exercise the shipped legacy Gateway update endpoint against a staged raw Distributor.

Run from a DVT checkout with the selected historical tag. The DinD image needs dockerd,
Docker Compose, curl and a POSIX shell. The candidate raw origin and bridge image
must be reachable from its daemon. All customer data is created inside that daemon.
"""

import argparse
import json
import secrets
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from scripts.release.test_install_candidate import host_docker

from services.installation_manager.application.legacy_import import SOURCE_REVISIONS

ROOT = Path(__file__).resolve().parents[2]
MANAGER = "cr.distribution.denvic.tech/dvt/installation_manager"
DATA = "/var/lib/dvt"


def wait_for(probe, description, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = probe()
        except (RuntimeError, ValueError):
            result = None
        if result:
            return result
        time.sleep(3)
    raise RuntimeError(f"Timed out waiting for {description}")


def run(args):
    name = f"dvt-legacy-acceptance-{uuid4().hex[:12]}"
    manifest = subprocess.check_output(
        ["git", "show", f"{args.source}:docker-compose.yaml"], cwd=ROOT,
    )
    if f"{MANAGER}:latest".encode() not in manifest:
        raise ValueError("Unexpected historical installation manager reference")

    def guest(*command, data=None):
        return host_docker("exec", "-i", name, *command, stdin=data, timeout=900)

    def request(path, payload=None):
        options = ["-H", "Content-Type: application/json", "--data-binary", "@-"] if payload is not None else []
        body = None if payload is None else json.dumps(payload).encode()
        raw = guest("curl", "-fsSL", "--max-time", "15", "-b", "/tmp/test.cookies",
                    "-c", "/tmp/test.cookies", *options, "http://127.0.0.1/api/" + path, data=body)
        return json.loads(raw or b"null")

    host_docker(
        "run", "-d", "--privileged", "--name", name, "-v", "/var/lib/docker",
        "-v", "/var/lib/containerd", args.dind_image,
    )
    try:
        wait_for(lambda: guest("docker", "info", "--format", "{{.ServerVersion}}"), "Docker", 90)
        guest("mkdir", "-p", DATA + "/installation", DATA + "/extensions", DATA + "/data/pgdata",
              DATA + "/data/valkeydata")
        guest("sh", "-c", "cat > /var/lib/dvt/docker-compose.yaml", data=manifest)
        instance = str(uuid4()).encode()
        guest("sh", "-c", "cat > /var/lib/dvt/installation/instance_id", data=instance)
        guest("docker", "network", "create", "dvt-net")
        build_env = (
            "from services.installation_manager.domain.models import InstallConfig; "
            "from services.installation_manager.domain.services import "
            "generate_fernet_key,generate_password,render_env_file; "
            f"print(render_env_file(InstallConfig(version={args.source!r},"
            "public_urls=['http://127.0.0.1'],fernet_key=generate_fernet_key(),"
            "postgres_password=generate_password(),valkey_password=generate_password(),"
            "grpc_token=generate_password(),task_workers_count=2)))"
        )
        env = guest("docker", "run", "--rm", "--entrypoint", "python3", f"{MANAGER}:{args.source}",
                    "-c", build_env)
        guest("sh", "-c", "umask 077; cat > /var/lib/dvt/.env",
              data=env + f"\nRAW_STORAGE_URL={args.raw_origin}\n".encode())
        # Recreate the old :latest reference as it existed when the customer installed DVT.
        # Leave the actual release Compose untouched so the updater backs up its original bytes.
        guest("docker", "tag", f"{MANAGER}:{args.source}", f"{MANAGER}:latest")
        guest("sh", "-c", "cat > /tmp/legacy-pull-policy.yaml",
              data=b"services:\n  installation_manager:\n    pull_policy: never\n")
        guest("docker", "compose", "--project-directory", DATA, "-p", "dvt",
              "-f", DATA + "/docker-compose.yaml", "-f", "/tmp/legacy-pull-policy.yaml",
              "up", "-d", "--scale", "task-worker=2")
        login = {"email": "acceptance@example.org", "password": secrets.token_urlsafe(22)}
        wait_for(lambda: guest("curl", "-fsS", "http://127.0.0.1/api/setup/status"), "old Gateway", 180)
        request("setup/superadmin", {"values": login})
        credentials = {"auth_provider": "email", **login}
        request("auth/sign-in", credentials)
        project = request("projects/", {"name": "Legacy release acceptance"})
        request(f"projects/{project['id']}/graph-ops", {"nodes_to_create": [{
            "id": "acceptance-node", "type": "base", "position": {"x": 10, "y": 10},
            "selected": False,
            "data": {"name": "ManageVariables", "displayName": "Manage Variables", "inputValues": {}},
        }]})

        def revision():
            return guest("docker", "exec", "dvt-postgres", "psql", "-U", "dvt-user", "-d", "DVT",
                         "-tAc", "SELECT version_num FROM alembic_version").decode().strip()

        assert revision() == SOURCE_REVISIONS[args.source]
        operation = request("update/run", {"version": args.target})["job_id"]

        def completed():
            request("auth/sign-in", credentials)
            status = request("update/status")
            if not status or status.get("id") != operation:
                return False
            if status.get("state") == "failed":
                raise AssertionError(f"Update {operation} failed: {status.get('error')}")
            if status.get("state") == "succeeded":
                catalog = request("update/releases")
                return catalog.get("source") == {"version": args.expected_version, "revision": args.revision}
            return False

        wait_for(completed, f"update {operation}", args.timeout)
        assert revision() == args.revision
        assert guest("cat", DATA + "/installation/instance_id").strip() == instance
        assert request(f"projects/{project['id']}")["name"] == project["name"]
        workers = guest("docker", "ps", "-q", "--filter", "label=com.docker.compose.project=dvt",
                        "--filter", "label=com.docker.compose.service=task-worker")
        assert len(workers.splitlines()) == 2
        tasks = f"projects/{project['id']}/tasks"
        task = request(tasks + "/new", {})["task_id"]

        def finished():
            state = request(f"{tasks}/{task}/info")["status"]
            if state in {"CANCELLED", "ERROR"}:
                raise AssertionError(f"Project task {task} ended in {state}")
            return state == "SUCCESS"

        wait_for(finished, "retained project execution", 120)
        print(f"{args.source} -> {args.expected_version}: job {operation}, task {task}, DB {args.revision}")
    finally:
        host_docker("rm", "-f", "-v", name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dind-image", required=True)
    parser.add_argument("--source", required=True, choices=SOURCE_REVISIONS)
    parser.add_argument("--raw-origin", required=True)
    parser.add_argument("--target", required=True, help="latest or exact stable version")
    parser.add_argument("--expected-version", required=True, help="Concrete published version")
    parser.add_argument("--revision", required=True, help="Target Alembic revision")
    parser.add_argument("--timeout", default=1800, type=int)
    run(parser.parse_args())
