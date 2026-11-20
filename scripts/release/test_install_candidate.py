"""Install an exact signed candidate in disposable Docker, then issue an install E2E receipt.

Requires a Docker host that permits a privileged disposable daemon. The test does not use
the host daemon for product containers, host ports, bind mounts or production credentials.
The receipt covers installation, readiness and first login, not the full AT matrix.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

DEFAULT_DIND = (
    "docker.io/library/docker@sha256:"
    "4bbc7223f81db790097c6dea42fb93e05b8fead4f0431fbe6ccaba6e8473201c"
)
DIGEST_IMAGE = re.compile(r"[a-z0-9][a-z0-9.:/_-]+@sha256:[a-f0-9]{64}")
TIMEOUT = 2400


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verified_inputs(manifest: Path, assets: Path, trust_path: Path):
    from services.installation_manager.domain.operation_state import ReleasePin
    from services.installation_manager.domain.release_manifest import (
        SignedRelease,
        digest_of,
        strict_json,
    )
    from services.installation_manager.infrastructure.release_verification import (
        MAX_MANIFEST_BYTES,
        TrustPolicy,
        verify_file,
    )

    content = manifest.read_bytes()
    require(len(content) <= MAX_MANIFEST_BYTES, "Manifest too large")
    envelope = SignedRelease.model_validate(strict_json(content))
    pin = ReleasePin(envelope.payload.release_id, digest_of(content))
    trust = TrustPolicy.from_document(strict_json(trust_path.read_bytes()))
    release = trust.verify(content, pin)
    require(set(release.platforms) == {"linux/amd64"}, "Only linux/amd64 is tested")
    require(
        release.database_schema.initial_install, "Candidate does not permit initial installation"
    )
    platform = release.platforms["linux/amd64"]
    files = {}
    for name, descriptor in (
        ("compose.yaml", platform.compose),
        ("bootstrap.py", platform.bootstrap),
    ):
        # Publisher's content-addressed packaged assets, never a source checkout fallback.
        relative = Path(urlsplit(descriptor.url).path.lstrip("/"))
        source = (assets / relative).resolve(strict=True)
        require(source.is_relative_to(assets.resolve()), "Packaged asset escapes its directory")
        data = source.read_bytes()
        verify_file(data, descriptor, name)
        files[name] = data
    return content, release, pin, files


def host_docker(*args: str, timeout: int = 600, stdin: bytes | None = None) -> bytes:
    # This function is only called by the outer driver for its uniquely named resources.
    environment = os.environ.copy()
    environment.pop("DOCKER_CONTEXT", None)
    result = subprocess.run(
        ["docker", *args],
        input=stdin,
        capture_output=True,
        timeout=timeout,
        env=environment,
        check=False,
    )
    if result.returncode:
        errors = re.findall(rb"^([A-Za-z]+(?:Error|Exception)):", result.stderr, re.MULTILINE)
        errors += re.findall(rb"Candidate install E2E failed \(([A-Za-z]+)\)", result.stderr)
        failure = errors[-1].decode("ascii") if errors else "command failure"
        for diagnostic in re.findall(
            rb"^DVT_INSTALL_FAILURE [a-z0-9_= -]+$",
            result.stderr,
            re.MULTILINE,
        ):
            print(diagnostic.decode("ascii"), file=sys.stderr)
        raise RuntimeError(f"Isolated Docker command failed ({args[0]}, {failure})")
    return result.stdout


def receipt(content: bytes, version: str, pipeline_id: str) -> dict:
    from services.installation_manager.domain.release_manifest import digest_of

    require(bool(re.fullmatch(r"[1-9][0-9]*", pipeline_id)), "Invalid pipeline ID")
    return {
        "format_version": 1,
        "version": version,
        "manifest_digest": digest_of(content),
        "result": "passed",
        "run_id": f"gitlab-pipeline-{pipeline_id}",
    }


def run_outer(args) -> None:
    content, release, _pin, files = verified_inputs(args.manifest, args.assets_dir, args.trust)
    expected = receipt(content, release.version, args.pipeline_id)
    require(not args.output.exists(), "Receipt output already exists")
    require(bool(DIGEST_IMAGE.fullmatch(args.dind_image)), "Pin the DinD infrastructure image")
    manager = release.platforms["linux/amd64"].images["installation_manager"].reference
    name = "dvt-install-e2e-" + uuid4().hex
    image = name + ":daemon"
    volume = name + "-case"
    started = False
    volume_created = False
    try:
        with tempfile.TemporaryDirectory(prefix="dvt-install-e2e-") as temporary:
            context = Path(temporary)
            # Real host OS for the nested daemon is the packaged manager's Debian image.
            # Static DinD runtime and Debian iptables support a private bridge and overlay store.
            (context / "Dockerfile").write_text(
                f"FROM {args.dind_image} AS binaries\nFROM {manager}\n"
                "COPY --from=binaries /usr/local/bin/ /usr/local/bin/\n"
                "RUN apt-get update && apt-get install -y --no-install-recommends iptables "
                "&& rm -rf /var/lib/apt/lists/*\n"
                'ENTRYPOINT ["dind", "dockerd"]\n',
                encoding="utf-8",
            )
            host_docker(
                "build", "--platform", "linux/amd64", "--tag", image, str(context), timeout=900
            )
            host_docker("volume", "create", "--label", f"dvt.install-e2e={name}", volume)
            volume_created = True
            host_docker(
                "run",
                "--detach",
                "--privileged",
                "--cgroupns=private",
                "--name",
                name,
                "--label",
                f"dvt.install-e2e={name}",
                "--env",
                "DOCKER_TLS_CERTDIR=",
                "--mount",
                f"type=volume,source={volume},target=/case",
                image,
                "--host=unix:///var/run/docker.sock",
                "--storage-driver=overlay2",
                "--data-root=/case/docker",
                "--feature=containerd-snapshotter=false",
                "--mtu=1400",
            )
            started = True
            # docker cp works against local and remote host daemons without host filesystem mounts.
            inputs = context / "input"
            inputs.mkdir()
            # The POSIX entrypoint normally persists this shell program beside bootstrap.py.
            launcher = (Path(__file__).resolve().parents[2] / "install.sh").read_text("utf-8")
            start = "runtime=$(cat <<'ROOT_SH'\n"
            _, found, rest = launcher.partition(start)
            shim, end, _ = rest.partition("\nROOT_SH\n)")
            require(bool(found and end and shim.strip()), "Missing managed host launcher")
            for filename, data in {
                **files,
                "host-launch.sh": shim.encode("utf-8"),
                "manifest.json": content,
                "trust.json": args.trust.read_bytes(),
                "test_install_candidate.py": Path(__file__).read_bytes(),
            }.items():
                (inputs / filename).write_bytes(data)
            if args.registry_config:
                config = json.loads(args.registry_config.read_bytes())
                require(
                    not config.get("credsStore") and not config.get("credHelpers"),
                    "Use an inline read-only registry auth config",
                )
                (inputs / "registry-config.json").write_text(json.dumps(config), encoding="utf-8")
            host_docker("cp", str(inputs), f"{name}:/case/input")
            deadline = time.monotonic() + 60
            while True:
                probe = subprocess.run(
                    [
                        "docker",
                        "exec",
                        name,
                        "docker",
                        "--host=unix:///var/run/docker.sock",
                        "info",
                    ],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                if probe.returncode == 0:
                    break
                require(time.monotonic() < deadline, "Disposable daemon did not become ready")
                time.sleep(1)
            host_docker(
                "exec",
                name,
                "python",
                "/case/input/test_install_candidate.py",
                "--controller",
                "--pipeline-id",
                args.pipeline_id,
                timeout=args.timeout,
            )
            host_docker("cp", f"{name}:/case/result.json", str(context / "result.json"))
            result = json.loads((context / "result.json").read_bytes())
            require(result == expected, "Test result does not bind the exact manifest")
        # Cleanup succeeds before a receipt becomes visible to the publisher.
        host_docker("rm", "--force", "--volumes", name)
        started = False
        host_docker("volume", "rm", volume)
        volume_created = False
        host_docker("image", "rm", image)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as output:
            output.write(json.dumps(expected, sort_keys=True).encode())
    finally:
        if started:
            host_docker("rm", "--force", "--volumes", name)
        if volume_created:
            host_docker("volume", "rm", volume)
        # This image tag is unique to the current test. Cleanup never enumerates runner objects.
        subprocess.run(
            ["docker", "image", "rm", image],
            capture_output=True,
            timeout=30,
            check=False,
        )


def finish_setup(product, setup_status: dict, email: str, password: str) -> None:
    """Follow the real wizard, including an organization already seeded by migration."""
    steps = {step["code"]: step for step in setup_status["steps"]}
    require(
        not setup_status["initialized"] and not steps["superadmin"]["completed"],
        "A fresh first administrator is required",
    )
    for step, fields in (
        ("organization", {"name": "Disposable release test"}),
        ("superadmin", {"email": email, "password": password}),
    ):
        if not steps[step]["completed"]:
            product.post(f"/api/setup/{step}", json={"values": fields}).raise_for_status()
    require(product.get("/api/setup/status").json()["initialized"], "Initial setup incomplete")


def controller(pipeline_id: str, progress: dict[str, str]) -> None:
    """Runs inside the unique daemon container; all Docker calls target its Unix socket."""
    import runpy
    import socket
    from types import SimpleNamespace

    import httpx
    from packaging.version import Version

    from services.installation_manager.application.offline_bundles import (
        LocalOnly,
        _preparer_version,
    )
    from services.installation_manager.application.online_operations import initial_settings
    from services.installation_manager.application.verified_staging import VerifiedStaging
    from services.installation_manager.candidate_auth import CandidateAuth
    from services.installation_manager.domain.operation_state import (
        ArtifactKind,
        OperationKind,
        OperationRequest,
        OperationStage,
    )
    from services.installation_manager.domain.release_manifest import (
        SignedRelease,
        digest_of,
        strict_json,
    )
    from services.installation_manager.host_bootstrap import (
        CONTROL,
        atomic_write,
        docker,
        load_host,
    )
    from services.installation_manager.infrastructure.operation_store import OperationStore
    from services.installation_manager.infrastructure.release_verification import (
        TrustPolicy,
        verify_file,
    )
    from services.installation_manager.infrastructure.staging_artifacts import (
        artifact_directory,
        save_config,
        write_artifact,
    )
    from services.installation_manager.infrastructure.staging_docker import StagingDocker
    from services.installation_manager.infrastructure.staging_host import HostPaths

    os.umask(0o077)
    inputs = Path("/case/input")
    content = (inputs / "manifest.json").read_bytes()
    envelope = SignedRelease.model_validate(strict_json(content))
    from services.installation_manager.domain.operation_state import ReleasePin

    pin = ReleasePin(envelope.payload.release_id, digest_of(content))
    trust = TrustPolicy.from_document(strict_json((inputs / "trust.json").read_bytes()))
    release = trust.verify(content, pin)
    platform = release.platforms["linux/amd64"]
    for name, descriptor in (
        ("compose.yaml", platform.compose),
        ("bootstrap.py", platform.bootstrap),
    ):
        verify_file((inputs / name).read_bytes(), descriptor, name)
    manager = platform.images["installation_manager"].reference
    auth_dir = Path("/root/.docker")
    auth_dir.mkdir(mode=0o700, exist_ok=True)
    auth_file = inputs / "registry-config.json"
    if auth_file.exists():
        atomic_write(auth_dir / "config.json", auth_file.read_bytes())
    docker("pull", "--platform", "linux/amd64", manager, timeout=600)
    bootstrap = runpy.run_path(str(inputs / "bootstrap.py"), run_name="packaged_bootstrap")
    # Supply the verified inputs normally passed by install.sh. Until publication the
    # exact candidate is staged locally, and does not need a live public catalog.
    project = "dvt-install-candidate"
    port = 8888
    public_host = socket.gethostbyname(socket.gethostname())
    data = Path("/case/data")
    root = docker("info", "--format", "{{.DockerRootDir}}").stdout.strip()
    host_record = f"{project}\n{manager}\n{root}\n\n{port}\n{release.version} {pin.manifest_digest}\n"
    atomic_write(inputs / "launch-host.conf", host_record.encode("ascii"))
    catalog_file = inputs / "catalog.json"
    atomic_write(catalog_file, json.dumps({
        "origin": "https://catalog.invalid",
        "trust": strict_json((inputs / "trust.json").read_bytes()),
    }).encode("utf-8"))
    # The daemon container is the actual disposable installation host. Bootstrap's
    # contained entry uses its OS release and its own backing store and Unix socket.
    Path("/run/dvt-host-os").write_bytes(Path("/etc/os-release").read_bytes())
    progress["phase"] = "bootstrap"
    bootstrap["bootstrap_with_lock"](
        SimpleNamespace(
            dir=str(data),
            project=project,
            port=port,
            public_url=f"http://{public_host}:8080",
            manager=manager,
            candidate=None,
            executor=None,
            cert=None,
            key=None,
            ca=None,
            containerd_root=None,
            temporary=None,
            backup=None,
            non_interactive=True,
            release_catalog_config=str(catalog_file),
            release_catalog_ca=None,
            new_pairing_token=False,
            local_images=True,
            quiet=True,
            managed=True,
            contained=True,
        )
    )
    config = load_host(data)
    control = data / CONTROL
    require(
        config.get("manager_http") is True and config["address"] == "0.0.0.0",
        "Candidate manager did not enable direct HTTP access",
    )
    require(
        not any((control / name).exists() for name in ("cert.pem", "key.pem", "ca.pem")),
        "HTTP bootstrap unexpectedly created manager certificates",
    )
    atomic_write(control / "release-trust.json", (inputs / "trust.json").read_bytes())
    cli_auth = control / "docker"
    cli_auth.mkdir(mode=0o700)
    if auth_file.exists():
        atomic_write(cli_auth / "config.json", auth_file.read_bytes())
    store = OperationStore.for_host(data)
    values = initial_settings() | {"DVT_ALLOW_PRERELEASE": "true"}
    request = OperationRequest(
        OperationKind.INSTALL,
        pin,
        config_id=save_config(store, values),
        task_workers_count=1,
        app_port=8080,
        ai_mcp_enabled=False,
    )
    operation = store.admit(request, idempotency_key=f"pipeline-{pipeline_id}")
    staging = artifact_directory(store, ArtifactKind.STAGING, operation.id)
    for name, source in (
        ("manifest.json", inputs / "manifest.json"),
        ("compose.yaml", inputs / "compose.yaml"),
        ("bootstrap.sh", inputs / "bootstrap.py"),
    ):
        write_artifact(staging / name, source.read_bytes())
    progress["phase"] = "staging"
    staged = VerifiedStaging(
        store,
        trust,
        LocalOnly(),
        StagingDocker(
            data,
            cli_auth,
            registry_hosts=frozenset(
                image.reference.split("/")[0] for image in platform.images.values()
            ),
        ),
        HostPaths(
            Path(config["temporary"]), Path(config["backup"]), os_release=Path("/etc/os-release")
        ),
        _preparer_version(),
        http_manager=True,
    ).prepare(operation.id, "", bootstrap_image=manager)
    # Ordinary detached executor applies the staged, signed full Compose and real migrator.
    progress["phase"] = "application"
    bootstrap["launch"](config, str(operation.id))
    deadline = time.monotonic() + 1500
    while time.monotonic() < deadline:
        state = store.get(operation.id)
        if state.stage is OperationStage.SUCCEEDED:
            break
        if state.stage.terminal or state.stage is OperationStage.RECOVERY_REQUIRED:
            events = store.events(operation.id)
            checkpoint = next((e.checkpoint for e in reversed(events) if e.checkpoint), None)
            reason = checkpoint.reason.value if checkpoint and checkpoint.reason else "unknown"
            print(f"DVT_INSTALL_FAILURE stage={state.stage.value} reason={reason}", file=sys.stderr)
            ids = docker(
                "container",
                "ls",
                "--all",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={config['project']}",
            ).stdout.split()
            if ids:
                for row in json.loads(docker("container", "inspect", *ids).stdout):
                    role = row["Config"]["Labels"].get("com.docker.compose.service", "unknown")
                    status = row["State"]["Status"]
                    health = row["State"].get("Health", {}).get("Status", "none")
                    if all(re.fullmatch(r"[a-z0-9-]+", value) for value in (role, status, health)):
                        print(
                            f"DVT_INSTALL_FAILURE service={role} state={status} health={health}",
                            file=sys.stderr,
                        )
            raise RuntimeError("Candidate installation failed")
        time.sleep(2)
    require(store.get(operation.id).stage is OperationStage.SUCCEEDED, "Installation timed out")
    progress["phase"] = "applied_identity"
    marker = strict_json((control / "current-release.json").read_bytes())
    require(
        marker["manifest_digest"] == pin.manifest_digest
        and marker["release_id"] == release.release_id
        and marker["version"] == release.version
        and marker["revision"] == release.database_schema.target_revision
        and marker["operation"] == str(operation.id)
        and marker["instance"] == str(store.identity().instance_id),
        "Installed release identity disagrees with signed candidate",
    )
    require(marker["images"] == staged.images, "Applied release lacks expected services")
    for role, reference in marker["images"].items():
        require(
            reference == platform.images[role].reference, "Applied service is outside signed images"
        )
    # Real HTTP boundary through the packaged proxy, including protected setup exchange.
    auth = CandidateAuth(config)
    progress["phase"] = "setup_pairing"
    require(auth.origin == f"http://{public_host}:{port}", "Unexpected manager origin")
    with httpx.Client(trust_env=False, timeout=15) as manager_http:
        manager_http.headers["Authorization"] = f"Bearer {auth.machine}"
        response = manager_http.post(
            f"{auth.origin}/api/operator/setup/{operation.id}/pairing",
            json={},
        )
        response.raise_for_status()
        setup_code = response.json()["code"]
    password = uuid4().hex + "aA9!"
    email = f"ci-{pipeline_id}@example.org"
    origin = config["public_url"]
    with httpx.Client(
        base_url=origin,
        trust_env=False,
        timeout=20,
        headers={
            "Origin": origin,
            "X-DVT-CSRF": "1",
        },
    ) as product:
        require(product.get("/api/health").json() == {"status": "ok"}, "Public health failed")
        html = product.get("/")
        require(
            html.status_code == 200 and "text/html" in html.headers["content-type"],
            "Packaged UI is unavailable",
        )
        progress["phase"] = "setup_exchange"
        response = product.post(
            "/api/setup/pairing",
            json={
                "operation_id": str(operation.id),
                "code": setup_code,
            },
        )
        response.raise_for_status()
        progress["phase"] = "setup_fields"
        finish_setup(product, response.json(), email, password)
        progress["phase"] = "first_login"
        login = product.post(
            "/api/auth/sign-in",
            json={
                "auth_provider": "email",
                "email": email,
                "password": password,
            },
        )
        login.raise_for_status()
        require(login.json().get("success") is True, "First login rejected")
        progress["phase"] = "authenticated_user"
        user = product.get("/api/user/info")
        user.raise_for_status()
        require(user.json()["email"] == email, "Authenticated first user differs")
        progress["phase"] = "public_version"
        version = product.get("/api/system/version")
        version.raise_for_status()
        require(
            Version(version.json()["version"]) == Version(release.version),
            "Public product version disagrees with manifest",
        )
    Path("/case/result.json").write_text(
        json.dumps(receipt(content, release.version, pipeline_id)),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--assets-dir", type=Path)
    parser.add_argument("--trust", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pipeline-id", required=True)
    parser.add_argument(
        "--registry-config", type=Path, help="Existing read-only inline Docker auth JSON"
    )
    parser.add_argument("--dind-image", default=DEFAULT_DIND)
    parser.add_argument("--timeout", type=int, default=TIMEOUT)
    parser.add_argument("--controller", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.controller:
        progress = {"phase": "inputs"}
        try:
            controller(args.pipeline_id, progress)
        except Exception as error:
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", 0)
            print(
                f"DVT_INSTALL_FAILURE phase={progress['phase']} error={type(error).__name__.lower()} status={status}",
                file=sys.stderr,
            )
            return 1
        return 0
    try:
        require(
            all((args.manifest, args.assets_dir, args.trust, args.output)),
            "Missing input paths",
        )
        require(60 <= args.timeout <= 3600, "Timeout outside 60–3600 seconds")
        run_outer(args)
    except Exception as error:  # HTTP errors may contain secrets; emit only the error type.
        print(
            f"Candidate install E2E failed ({type(error).__name__}); no receipt issued",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
