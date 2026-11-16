"""Host-side entrypoint for the opt-in installation manager candidate (stdlib only)."""

# ruff: noqa: T201 - bootstrap writes results to the administrator's terminal

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SOCKET = "/var/run/docker.sock"
IMAGE = re.compile(r"[a-z0-9][a-z0-9.:-]*/[a-z0-9/_-]+(?:[.][a-z0-9/_-]+)*@sha256:[0-9a-f]{64}")
PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
DOCKER_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "LANG": "C.UTF-8",
}
UNIT_DIR = Path("/etc/systemd/system")
CONTROL = ".bootstrap"
STATE = ".installation-state"


def command(args, *, check=True, timeout=180):
    with subprocess.Popen(
        args,
        env=DOCKER_ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
        result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result


def docker(*args, **kwargs):
    return command(["docker", "--host", f"unix://{SOCKET}", *args], **kwargs)


def check_image(reference, *, pull=False):
    if not isinstance(reference, str) or not IMAGE.fullmatch(reference):
        raise ValueError("An approved registry image pinned by SHA-256 is required")
    result = docker("image", "inspect", reference, check=False)
    if result.returncode and pull:
        docker("pull", "--platform", "linux/amd64", reference, timeout=600)
        result = docker("image", "inspect", reference)
    if result.returncode:
        raise ValueError("The approved image is not available locally")
    (image,) = json.loads(result.stdout)
    if reference not in (image["RepoDigests"] or []) or (image["Os"], image["Architecture"]) != (
        "linux",
        "amd64",
    ):
        raise ValueError("Docker did not confirm the approved image digest and platform")
    return image["Id"]


def safe_path(path):
    p = Path(path)
    if p == Path("/") or not re.fullmatch(r"/[a-zA-Z0-9_./-]+", str(p)) or not p.is_absolute():
        raise ValueError("Expected an absolute Linux path without spaces or delimiters")
    if p != p.resolve():
        raise ValueError("Use the canonical path without symlink components")
    for entry in [p, *p.parents]:
        if entry.exists():
            mode = entry.lstat()
            # A sticky root-owned parent (e.g. /var/tmp) protects root-owned children.
            writable_parent = mode.st_mode & 0o022 and not mode.st_mode & stat.S_ISVTX
            if mode.st_uid or writable_parent or (entry == p and mode.st_mode & 0o022):
                raise ValueError(f"Root ownership and protected permissions are required: {entry}")
    return p


def atomic_write(path, content, mode=0o600):
    fd, temp = tempfile.mkstemp(prefix=".new-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            if os.name == "posix":
                os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temp).replace(path)
        if os.name == "posix":
            dir_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        Path(temp).unlink(missing_ok=True)


def load_host(data):
    path = data / CONTROL / "host.json"
    for entry, mode, kind in ((path.parent, 0o700, stat.S_ISDIR), (path, 0o600, stat.S_ISREG)):
        info = entry.lstat()
        if info.st_uid or stat.S_IMODE(info.st_mode) != mode or not kind(info.st_mode):
            raise PermissionError("Bootstrap configuration ownership or mode is invalid")
    value = json.loads(path.read_bytes())
    if (
        value["version"] != 1
        or value["data"] != str(data)
        or not PROJECT.fullmatch(value["project"])
    ):
        raise ValueError("Invalid host configuration")
    return value


def candidate(config):
    encoded = json.dumps(
        {
            "format_version": 1,
            "profile": "manager-handoff-only",
            "platform": "linux/amd64",
            "source_image": config["manager"],
            "target_image": config["candidate"],
            "executor_image": config["executor"],
            "journal_format": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "manager-handoff-v1", "sha256:" + hashlib.sha256(encoded).hexdigest()


def mount(source, target=None, *, readonly=False):
    return f"type=bind,source={source},target={target or source}" + (
        ",readonly" if readonly else ""
    )


def container_name(config):
    return f"dvt-bootstrap-executor-{config['instance']}"


def launch(config, operation_id):
    import fcntl

    with (Path(config["data"]) / CONTROL / "launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _launch(config, operation_id)


def _launch(config, operation_id):
    check_image(config["executor"])
    name = container_name(config)
    existing = docker("container", "inspect", name, check=False)
    if existing.returncode == 0:
        (current,) = json.loads(existing.stdout)
        labels = current["Config"]["Labels"] or {}
        if (
            labels.get("dvt.executor.instance") != config["instance"]
            or labels.get("dvt.executor.operation") != operation_id
            or current["Config"]["Image"] != config["executor"]
        ):
            raise RuntimeError("The executor name belongs to a different container")
        if current["State"]["Running"]:
            return
        docker("container", "rm", name)
    docker_info = json.loads(docker("info", "--format", "{{json .}}").stdout)
    if docker_info["DockerRootDir"] != config["docker_root"]:
        raise ValueError("Docker data root has changed since host preparation")
    if image_store(docker_info) != bool(config["containerd_root"]):
        raise ValueError("Docker image store has changed since host preparation")
    mounts = [
        mount(config["data"]),
        mount(SOCKET),
        mount("/etc/os-release", "/run/dvt-host-os", readonly=True),
    ]
    for directory in dict.fromkeys([config["docker_root"], config["containerd_root"]]):
        if directory:
            mounts.append(mount(directory, readonly=True))
    for directory in dict.fromkeys([config["temporary"], config["backup"]]):
        if directory != config["data"] and not Path(directory).is_relative_to(config["data"]):
            mounts.append(mount(directory))
    args = [
        "run",
        "--detach",
        "--rm",
        "--pull=never",
        "--network",
        "host",
        "--name",
        name,
        "--label",
        f"dvt.executor.instance={config['instance']}",
        "--label",
        f"dvt.executor.operation={operation_id}",
    ]
    for item in mounts:
        args.extend(("--mount", item))
    docker(*args, config["executor"], "candidate-executor", config["data"], operation_id)


def active_id(config):
    journal = Path(config["data"]) / STATE / "journal.sqlite3"
    if not journal.exists():
        return None
    if any(
        entry.lstat().st_uid
        or stat.S_IMODE(entry.lstat().st_mode) != mode
        or not kind(entry.lstat().st_mode)
        for entry, mode, kind in (
            (journal.parent, 0o700, stat.S_ISDIR),
            (journal, 0o600, stat.S_ISREG),
        )
    ):
        raise ValueError("Unsafe installation journal")
    with contextlib.closing(sqlite3.connect(f"{journal.as_uri()}?mode=rw", uri=True)) as db:
        if (
            db.execute("PRAGMA application_id").fetchone()[0] != 0x44565449
            or db.execute("PRAGMA user_version").fetchone()[0] != 1
        ):
            raise ValueError("Unsupported installation journal")
        row = db.execute(
            "SELECT id FROM operations WHERE instance_id = ? AND finished_at IS NULL",
            (config["instance"],),
        ).fetchone()
        return row[0] if row else None


def image_store(info):
    return ["driver-type", "io.containerd.snapshotter.v1"] in (info.get("DriverStatus") or [])


def check_port(address, port):
    with socket.socket() as probe:
        probe.bind((address, port))


def check_project(project):
    for kind in ("container", "network", "volume"):
        flags = ["--all"] if kind == "container" else []
        if docker(
            kind, "ls", *flags, "--quiet", "--filter", f"label=com.docker.compose.project={project}"
        ).stdout.strip():
            raise ValueError("The Compose project name is already in use")


def docker_ready():
    return (
        shutil.which("docker", path=DOCKER_ENV["PATH"])
        and Path(SOCKET).is_socket()
        and docker("info", check=False, timeout=20).returncode == 0
        and docker("compose", "version", check=False, timeout=20).returncode == 0
    )


def install_docker(allowed, interactive):
    if docker_ready():
        return
    print("Docker Engine and Compose are required. Package installation needs root.")
    if not allowed and not (
        interactive
        and input("Install Docker from Docker's signed APT repository? [y/N] ").lower() == "y"
    ):
        raise ValueError("Docker preparation needs explicit permission (--install-docker)")
    # Use Docker's key only after matching the published primary fingerprint.
    distro = dict(
        line.split("=", 1)
        for line in Path("/etc/os-release").read_text().splitlines()
        if "=" in line
    )
    name, codename = distro["ID"].strip('"'), distro["VERSION_CODENAME"].strip('"')
    if (name, codename) not in {("debian", "trixie"), ("ubuntu", "noble")}:
        raise ValueError("Docker preparation supports Debian 13 and Ubuntu 24.04")
    with tempfile.TemporaryDirectory() as folder:
        key = Path(folder) / "docker.asc"
        command(["apt-get", "update"])
        command(["apt-get", "install", "-y", "ca-certificates", "curl", "gpg"])
        command(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--proto",
                "=https",
                "--output",
                str(key),
                f"https://download.docker.com/linux/{name}/gpg",
            ]
        )
        fingerprints = command(
            ["gpg", "--batch", "--homedir", folder, "--with-colons", "--show-keys", str(key)]
        ).stdout.splitlines()
        primary = [
            (row.split(":")[0], row.split(":")[9])
            for row in fingerprints
            if row.startswith(("pub:", "sub:", "fpr:"))
        ]
        if len([row for row in primary if row[0] == "pub"]) != 1 or primary[1] != (
            "fpr",
            "9DC858229FC7DD38854AE2D88D81803C0EBFCD88",
        ):
            raise ValueError("The Docker APT signing key did not match the pinned fingerprint")
        keyring = Path("/etc/apt/keyrings/dvt-docker.asc")
        keyring.parent.mkdir(mode=0o755, exist_ok=True)
        atomic_write(keyring, key.read_bytes(), 0o644)
    source = (
        f"deb [arch=amd64 signed-by={keyring}] "
        f"https://download.docker.com/linux/{name} {codename} stable\n"
    )
    atomic_write(Path("/etc/apt/sources.list.d/dvt-docker.list"), source.encode(), 0o644)
    command(["apt-get", "update"])
    command(
        [
            "apt-get",
            "install",
            "-y",
            "docker-ce",
            "docker-ce-cli",
            "containerd.io",
            "docker-compose-plugin",
        ],
        timeout=600,
    )
    if not docker_ready():
        raise RuntimeError("Docker Engine or Compose remains unavailable")


def manager_compose(config, image):
    data = Path(config["data"])
    return {
        "services": {
            "installation_manager": {
                "image": image,
                "restart": "unless-stopped",
                "ports": [
                    {
                        "target": 8000,
                        "published": str(config["port"]),
                        "host_ip": config["address"],
                        "protocol": "tcp",
                    }
                ],
                "command": ["candidate-web", str(data)],
                "volumes": [
                    {"type": "bind", "source": str(p), "target": str(p)}
                    for p in (data, Path(SOCKET))
                ],
            },
        },
    }


def apply_manager(config, image, path):
    atomic_write(path, json.dumps(manager_compose(config, image)).encode())
    # This Compose has only the fixture manager; no application/migration services.
    docker(
        "compose",
        "--project-name",
        config["project"],
        "--project-directory",
        config["data"],
        "--env-file",
        "/dev/null",
        "--file",
        str(path),
        "up",
        "--detach",
        "--pull",
        "never",
        timeout=90,
    )


def init_container(config, action):
    result = docker(
        "run",
        "--rm",
        "--pull=never",
        "--network",
        "none",
        "--mount",
        mount(config["data"]),
        config["manager"],
        action,
        config["data"],
    )
    return result.stdout.strip()


def install_unit(data, config):
    control = data / CONTROL
    script = control / "host_bootstrap.py"
    unit = UNIT_DIR / f"dvt-bootstrap-{config['project']}.service"
    atomic_write(script, Path(__file__).read_bytes())
    content = f"""[Unit]
Description=DVT resume for {config["project"]}
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {script} resume --dir {data}

[Install]
WantedBy=multi-user.target
""".encode()
    if unit.exists() and unit.read_bytes() != content:
        raise ValueError("A different resume service already owns this project")
    if not unit.exists():
        atomic_write(unit, content, 0o644)
    command(["systemctl", "daemon-reload"])
    command(["systemctl", "enable", unit.name])


def bootstrap(args):
    from uuid import uuid4

    data = safe_path(args.dir)
    config_path = data / CONTROL / "host.json"
    prior = load_host(data) if config_path.exists() else None
    if not args.non_interactive:
        for key, label in (
            ("project", "Compose project"),
            ("port", "HTTPS port"),
            ("public_url", "Public DVT origin"),
            ("manager", "Approved bootstrap manager image"),
            ("candidate", "Approved target manager image"),
            ("executor", "Approved executor image"),
            ("cert", "TLS certificate path"),
            ("key", "TLS private key path"),
            ("ca", "TLS CA path"),
            ("containerd_root", "Containerd data root (if enabled)"),
        ):
            if getattr(args, key) is None and prior is None:
                default = {"project": "dvt", "port": "8888"}.get(key, "")
                reply = input(f"{label} [{default}] ").strip() or default
                setattr(args, key, int(reply) if key == "port" else reply or None)
    project = args.project or (prior["project"] if prior else "dvt")
    port = args.port if args.port is not None else (prior["port"] if prior else 8888)
    public_url = args.public_url or (prior["public_url"] if prior else None)
    if not PROJECT.fullmatch(project) or not 1024 <= port <= 65535:
        raise ValueError("Invalid Compose project name or HTTPS port (1024–65535)")
    if prior:
        for key in (
            "project",
            "port",
            "public_url",
            "manager",
            "candidate",
            "executor",
            "containerd_root",
            "temporary",
            "backup",
        ):
            supplied = getattr(args, key)
            if supplied is not None and supplied != prior[key]:
                raise ValueError(f"A different value is already stored for {key}")
        for name in ("cert", "key", "ca"):
            supplied = getattr(args, name)
            if (
                supplied
                and Path(supplied).read_bytes() != (data / CONTROL / f"{name}.pem").read_bytes()
            ):
                raise ValueError("The supplied TLS material differs from the stored configuration")
        config = prior
        docker_ready_now = docker_ready()
        if not docker_ready_now:
            raise ValueError("Docker or Compose is unavailable for the existing instance")
        init_container(config, "candidate-init")
        install_unit(data, config)
        for key in ("temporary", "backup"):
            safe_path(config[key]).mkdir(mode=0o700, parents=True, exist_ok=True)
        operation = active_id(config)
        if operation:
            launch(config, operation)
        elif not docker(
            "container",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            "label=com.docker.compose.service=installation_manager",
        ).stdout.strip():
            # Launch the last verified manager if the running container was removed.
            installed = (data / CONTROL / "current-manager").read_text().strip()
            check_image(installed)
            apply_manager(config, installed, data / CONTROL / "bootstrap.compose.yaml")
    else:
        if UNIT_DIR.joinpath(f"dvt-bootstrap-{project}.service").exists():
            raise ValueError("A bootstrap instance already reserves this Compose project")
        if data.exists() and (
            not data.is_dir()
            or any(
                not entry.name.startswith(".bootstrap-partial-")
                or not entry.is_dir()
                or safe_path(entry) != entry
                for entry in data.iterdir()
            )
        ):
            raise ValueError("The selected data directory is not empty")
        check_port("127.0.0.1", port)
        if docker_ready():
            check_project(project)
        if not all((args.manager, args.candidate, args.executor, args.cert, args.key, args.ca)):
            raise ValueError("Supply approved image digests and HTTPS certificate, key and CA")
        if any(not IMAGE.fullmatch(img) for img in (args.manager, args.candidate, args.executor)):
            raise ValueError("Supply explicit registry references pinned by SHA-256 digest")
        if args.manager == args.candidate:
            raise ValueError("The candidate requires a distinct manager image")
        from urllib.parse import urlsplit

        public_url = public_url or f"https://localhost:{port}"
        url = urlsplit(public_url)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username is not None
            or url.path not in ("", "/")
            or url.query
            or url.fragment
            or any(char.isspace() or char in "?#\\" for char in public_url)
        ):
            raise ValueError("Expected a public DVT HTTP(S) origin")
        _ = url.port
        tls = {name: Path(getattr(args, name)).read_bytes() for name in ("cert", "key", "ca")}
        install_docker(args.install_docker, not args.non_interactive)
        check_project(project)
        info = json.loads(docker("info", "--format", "{{json .}}").stdout)
        root = safe_path(info["DockerRootDir"])
        containerd = safe_path(args.containerd_root) if args.containerd_root else None
        if image_store(info) != bool(containerd):
            raise ValueError(
                "For the enabled containerd image store supply its actual --containerd-root"
            )
        if not root.is_dir() or (containerd is not None and not containerd.is_dir()):
            raise ValueError("Docker backing directories are unavailable")
        temporary = safe_path(args.temporary or str(data / "tmp"))
        backup = safe_path(args.backup or str(data / "backup"))
        for path in (data, temporary, backup):
            if any(
                path.is_relative_to(backing) or backing.is_relative_to(path)
                for backing in (root, containerd)
                if backing is not None
            ):
                raise ValueError(
                    "DVT data, temporary and backup paths must be separate from Docker storage"
                )
        if (
            len({data, temporary, backup}) != 3
            or data.is_relative_to(temporary)
            or data.is_relative_to(backup)
        ):
            raise ValueError("Choose separate data, temporary and backup directories")
        for img in dict.fromkeys([args.manager, args.candidate, args.executor]):
            check_image(img, pull=True)
        data.mkdir(mode=0o700, parents=True, exist_ok=True)
        control = data / CONTROL
        config = {
            "version": 1,
            "instance": str(uuid4()),
            "data": str(data),
            "project": project,
            "address": "127.0.0.1",
            "port": port,
            "public_url": public_url,
            "manager": args.manager,
            "candidate": args.candidate,
            "executor": args.executor,
            "docker_root": str(root),
            "containerd_root": str(containerd) if containerd else None,
            "temporary": str(temporary),
            "backup": str(backup),
        }
        with tempfile.TemporaryDirectory(prefix=".bootstrap-partial-", dir=data) as folder:
            staging = Path(folder)
            for name, value in tls.items():
                atomic_write(staging / f"{name}.pem", value)
            atomic_write(staging / "current-manager", config["manager"].encode())
            atomic_write(staging / config_path.name, json.dumps(config).encode())
            staging.rename(control)
            dir_fd = os.open(data, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        for path in (temporary, backup):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        init_container(config, "candidate-init")
        install_unit(data, config)
        apply_manager(config, config["manager"], control / "bootstrap.compose.yaml")
    print(f"Manager: https://localhost:{config['port']} (127.0.0.1)")
    print(f"Instance: {config['instance']} · {data} · {config['project']}")
    if not prior or args.new_pairing_token:
        if not sys.stdout.isatty():
            print(
                "Issue the pairing code from an administrative terminal using --new-pairing-token."
            )
        else:
            print("Enter this pairing code in the browser within 10 minutes:")
            print(init_container(config, "candidate-pair"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["bootstrap", "resume"])
    parser.add_argument("--dir", default="/var/lib/dvt")
    parser.add_argument("--project")
    parser.add_argument("--port", type=int)
    parser.add_argument("--public-url")
    for key in (
        "manager",
        "candidate",
        "executor",
        "cert",
        "key",
        "ca",
        "containerd-root",
        "temporary",
        "backup",
    ):
        parser.add_argument(f"--{key}")
    for key in ("non-interactive", "install-docker", "new-pairing-token"):
        parser.add_argument(f"--{key}", action="store_true")
    args = parser.parse_args()
    try:
        os.umask(0o077)
        if os.geteuid() or not sys.platform.startswith("linux") or platform.machine() != "x86_64":
            raise ValueError("This candidate requires root on Linux amd64")
        if not Path("/run/systemd/system").is_dir():
            raise ValueError("The host must run systemd")
        if args.action == "resume":
            config = load_host(safe_path(args.dir))
            if operation := active_id(config):
                launch(config, operation)
        else:
            import fcntl

            lock_dir = Path("/run/dvt-bootstrap")
            lock_dir.mkdir(mode=0o700, exist_ok=True)
            safe_path(lock_dir)
            with (lock_dir / "bootstrap.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                bootstrap(args)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, sqlite3.Error) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(
                f"Bootstrap command failed ({Path(error.cmd[0]).name}, status {error.returncode})",
                file=sys.stderr,
            )
        else:
            print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
