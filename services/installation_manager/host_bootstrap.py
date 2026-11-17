"""Host-side entrypoint for the protected installation manager (stdlib only)."""

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
import ssl
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

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
LAUNCH_DIGEST = "launch-bootstrap.sha256"
HOST_OS_RELEASE = Path("/run/dvt-host-os")


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
    aliases = {reference}
    if reference.startswith("docker.io/"):
        short = reference.removeprefix("docker.io/")
        aliases.update((f"index.docker.io/{short}", short))
        if short.startswith("library/"):
            aliases.add(short.removeprefix("library/"))
    if not aliases.intersection(image["RepoDigests"] or []) or (
        image["Os"], image["Architecture"]
    ) != ("linux", "amd64"):
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


def launch(config, operation_id, action="candidate-executor"):
    import fcntl

    with (Path(config["data"]) / CONTROL / "launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _launch(config, operation_id, action)


def _launch(config, operation_id, action="candidate-executor"):
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
            if action != "candidate-executor":
                raise RuntimeError("The operation executor is already running; retry after it exits")
            return
        docker("container", "rm", name)
    docker_info = json.loads(docker("info", "--format", "{{json .}}").stdout)
    if docker_info["DockerRootDir"] != config["docker_root"]:
        raise ValueError("Docker data root has changed since host preparation")
    if image_store(docker_info) != bool(config["containerd_root"]):
        raise ValueError("Docker image store has changed since host preparation")
    if action == "candidate-executor":
        restore_initial_manager(config, operation_id)
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
    docker(*args, config["executor"], action, config["data"], operation_id)


def active_operation(config):
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
        return db.execute(
            "SELECT id, stage, request FROM operations WHERE instance_id = ? AND finished_at IS NULL",
            (config["instance"],),
        ).fetchone()


def active_id(config):
    row = active_operation(config)
    return row[0] if row else None


def restore_initial_manager(config, operation_id):
    from uuid import UUID

    if not config.get("release_catalog"):
        return
    active = active_operation(config)
    if active is None or active[0] != operation_id or active[1] not in {"admitted", "preparing"}:
        return
    request = json.loads(active[2])
    if request["kind"] != "install" or request["bundle_id"] is not None or not request["config_id"]:
        return

    data = Path(config["data"])
    control = data / CONTROL
    config_id = str(UUID(request["config_id"]))
    operator = data / STATE / "artifacts" / "config" / config_id / "operator.json"
    current_release = control / "current-release.json"
    if not operator.is_file() or operator.is_symlink() or current_release.exists() or current_release.is_symlink():
        return
    if docker(
        "container", "ls", "--all", "--quiet",
        "--filter", f"label=com.docker.compose.project={config['project']}",
    ).stdout.strip():
        return
    marker = control / "current-manager"
    info = marker.lstat()
    if info.st_uid or stat.S_IMODE(info.st_mode) != 0o600 or not stat.S_ISREG(info.st_mode):
        raise ValueError("Unsafe bootstrap manager digest file")
    installed = marker.read_text().strip()
    if installed not in {config["manager"], config["candidate"]}:
        raise ValueError("The local bootstrap manager differs from the approved digests")
    check_image(installed)
    apply_manager(config, installed, control / "bootstrap.compose.yaml")


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


def start_verified_manager(config):
    if docker(
        "container",
        "ls",
        "--quiet",
        "--filter",
        f"label=com.docker.compose.project={config['project']}",
        "--filter",
        "label=com.docker.compose.service=installation_manager",
    ).stdout.strip():
        return
    control = Path(config["data"]) / CONTROL
    installed = (control / "current-manager").read_text().strip()
    check_image(installed)
    apply_manager(config, installed, control / "bootstrap.compose.yaml")


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


def _catalog_config(path, os_release=Path("/etc/os-release")):
    with Path(path).open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("The release catalog configuration is too large")
    settings = json.loads(raw)
    if not isinstance(settings, dict) or set(settings) - {
        "origin", "trust", "registry_hosts", "asset_origins",
    }:
        raise ValueError("Unsupported release catalog configuration field")
    origin = settings.get("origin")
    if not isinstance(origin, str) or not 0 < len(origin) <= 2048:
        raise ValueError("The release catalog requires an HTTPS origin")
    url = urlsplit(origin)
    if (
        url.scheme != "https" or not url.hostname or url.username is not None
        or url.path not in ("", "/")
        or any(char.isspace() or ord(char) < 32 or char in "?#\\" for char in origin)
    ):
        raise ValueError("The release catalog requires a credential-free HTTPS origin")
    port = url.port
    authority = url.netloc.lower()
    settings["origin"] = "https://" + (authority.removesuffix(":443") if port == 443 else authority)
    registries = settings.get("registry_hosts", [])
    assets = settings.get("asset_origins", [])
    if not isinstance(registries, list) or len(registries) > 16 or any(
        not isinstance(host, str)
        or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)+(?:\:[0-9]{1,5})?", host)
        or (":" in host and not 1 <= int(host.rsplit(":", 1)[1]) <= 65535)
        for host in registries
    ):
        raise ValueError("Registry allowlist entries must be explicit DNS hosts with optional ports")
    if not isinstance(assets, list) or len(assets) > 16:
        raise ValueError("Invalid release asset origin allowlist")
    for asset in assets:
        if not isinstance(asset, str) or not re.fullmatch(
            r"https://[a-z0-9]+(?:[.-][a-z0-9]+)+(?:\:[0-9]{1,5})?", asset
        ):
            raise ValueError("Asset allowlist entries must be explicit HTTPS origins")
        parsed = urlsplit(asset)
        if parsed.port == 0:
            raise ValueError("Invalid release asset port")
    settings["asset_origins"] = [asset.removesuffix(":443") for asset in assets]
    trust = settings.get("trust")
    if trust is not None and (
        not isinstance(trust, dict) or set(trust) != {"roots", "revoked_signers"}
        or not isinstance(trust["roots"], dict) or not trust["roots"]
        or not isinstance(trust["revoked_signers"], list)
        or any(
            not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
            for key in trust["roots"].values()
        )
        or any(
            not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
            for value in trust["revoked_signers"]
        )
    ):
        raise ValueError("The DVT release trust document is invalid")
    distro = dict(
        line.split("=", 1)
        for line in os_release.read_text().splitlines()
        if "=" in line
    )
    distribution = distro.get("ID", "").strip('"')
    version = distro.get("VERSION_ID", "").strip('"')
    if not distribution or not version:
        raise ValueError("The host Linux distribution or version is unknown")
    return {
        **settings,
        "platform": "linux/amd64",
        "distribution": distribution,
        "distribution_version": version,
    }


def bootstrap_images(args, *, catalog):
    if catalog is not None and args.candidate is None:
        # Catalog operations select their target from the signed release after bootstrap.
        return args.manager, args.manager, args.executor or args.manager
    if (
        args.candidate is not None
        and args.manager == args.candidate
        and not getattr(args, "local_images", False)
    ):
        raise ValueError("The manager handoff requires a distinct target image")
    return args.manager, args.candidate, args.executor


def managed_tls(directory):
    ca, ca_key, cert, key, request, extensions = (
        directory / name for name in ("ca.pem", "ca.key", "cert.pem", "key.pem", "host.csr", "host.ext")
    )
    extensions.write_text(
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectAltName=DNS:localhost,IP:127.0.0.1\n"
    )
    command([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "3650",
        "-subj", "/CN=DVT local installation CA",
        "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        "-keyout", str(ca_key), "-out", str(ca),
    ])
    command([
        "openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
        "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(request),
    ])
    command([
        "openssl", "x509", "-req", "-in", str(request), "-CA", str(ca), "-CAkey", str(ca_key),
        "-set_serial", f"0x{os.urandom(16).hex()}", "-sha256", "-days", "825",
        "-extfile", str(extensions), "-out", str(cert),
    ])
    command(["openssl", "verify", "-CAfile", str(ca), "-verify_hostname", "localhost", str(cert)])
    return {name: path.read_bytes() for name, path in (("cert", cert), ("key", key), ("ca", ca))}


def print_managed_access(data, port):
    ca_path = data / CONTROL / "ca.pem"
    ca = ssl.PEM_cert_to_DER_cert(ca_path.read_text(encoding="ascii"))
    fingerprint = hashlib.sha256(ca).hexdigest()
    print("On your workstation, verify the server SSH host key, then run:")
    print(f"  ssh -N -L 127.0.0.1:{port}:127.0.0.1:{port} administrator@dvt-host")
    print(f"  ssh -t administrator@dvt-host 'sudo cat -- {ca_path}' | tr -d '\\r' \\")
    print("    | sed -n '/^-----BEGIN CERTIFICATE-----$/,/^-----END CERTIFICATE-----$/p' "
          "> dvt-manager-ca.pem")
    print("  openssl x509 -in dvt-manager-ca.pem -noout -sha256 -fingerprint")
    print("Verify the CA SHA-256 fingerprint, then trust this CA in your browser:")
    print("  " + ":".join(fingerprint[i:i + 2] for i in range(0, len(fingerprint), 2)).upper())


def bootstrap(args):
    from uuid import uuid4

    data = safe_path(args.dir)
    config_path = data / CONTROL / "host.json"
    prior = load_host(data) if config_path.exists() else None
    contained = getattr(args, "contained", False)
    catalog_file = getattr(args, "release_catalog_config", None)
    os_release = HOST_OS_RELEASE if contained else Path("/etc/os-release")
    catalog = _catalog_config(catalog_file, os_release) if catalog_file else None
    catalog_ca_path = getattr(args, "release_catalog_ca", None)
    catalog_ca = None
    if catalog_ca_path:
        if catalog is None and (prior is None or "release_catalog" not in prior):
            raise ValueError("Select an HTTPS release catalog before providing its trust CA")
        with Path(catalog_ca_path).open("rb") as stream:
            catalog_ca = stream.read(128 * 1024 + 1)
        if not 0 < len(catalog_ca) <= 128 * 1024:
            raise ValueError("The release catalog CA file is empty or too large")
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(
            cadata=catalog_ca.decode("ascii")
        )
    managed = getattr(args, "managed", False)
    launch_digest = None
    if managed:
        if not contained:
            raise ValueError("Use the POSIX installer for the managed path")
        launch_source = Path(__file__)
        launch_content = launch_source.read_bytes()
        launch_digest = hashlib.sha256(launch_content).hexdigest()
        if prior:
            previous_digest = (data / CONTROL / LAUNCH_DIGEST).read_text(encoding="ascii")
            if previous_digest != launch_digest:
                raise ValueError("The saved managed bootstrap differs; rerun the public command")
            if catalog is not None and catalog["origin"] != prior["release_catalog"]["origin"]:
                raise ValueError("A different release catalog origin is already stored")
            args.manager, catalog, catalog_ca = None, None, None
        elif catalog is None or args.candidate is not None or args.executor is not None:
            raise ValueError("A managed installation needs an approved release catalog and manager")
    use_catalog_images = catalog is not None and args.candidate is None
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
            if (
                (use_catalog_images and key in {"candidate", "executor"})
                or (managed and key in {"cert", "key", "ca", "containerd_root"})
            ):
                continue
            if getattr(args, key) is None and prior is None:
                default = {
                    "project": "dvt", "port": "8888",
                    "public_url": "http://localhost" if managed else "",
                }.get(key, "")
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
        if catalog is not None:
            existing = config.get("release_catalog")
            if existing is not None and existing["origin"] != catalog["origin"]:
                raise ValueError("A different release catalog origin is already stored")
            config = {**config, "release_catalog": catalog}
        docker_ready_now = docker_ready()
        if not docker_ready_now:
            raise ValueError("Docker or Compose is unavailable for the existing instance")
        if catalog_ca is not None:
            atomic_write(data / CONTROL / "release-catalog-ca.pem", catalog_ca)
        if config != prior:
            atomic_write(config_path, json.dumps(config).encode())
        init_container(config, "candidate-init")
        if not contained:
            install_unit(data, config)
        for key in ("temporary", "backup"):
            safe_path(config[key]).mkdir(mode=0o700, parents=True, exist_ok=True)
        operation = active_id(config)
        if operation:
            launch(config, operation)
        else:
            start_verified_manager(config)
    else:
        if not contained and UNIT_DIR.joinpath(f"dvt-bootstrap-{project}.service").exists():
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
        manager, candidate_image, executor = bootstrap_images(args, catalog=catalog)
        if not all((manager, candidate_image, executor)):
            raise ValueError("Supply approved image digests")
        if not managed and not all((args.cert, args.key, args.ca)):
            raise ValueError("Supply the HTTPS certificate, key and CA")
        if any(not IMAGE.fullmatch(img) for img in (manager, candidate_image, executor)):
            raise ValueError("Supply explicit registry references pinned by SHA-256 digest")
        public_url = public_url or ("http://localhost" if managed else f"https://localhost:{port}")
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
        if managed:
            with tempfile.TemporaryDirectory(prefix="dvt-tls-", dir="/tmp") as folder:
                tls = managed_tls(Path(folder))
        else:
            tls = {name: Path(getattr(args, name)).read_bytes() for name in ("cert", "key", "ca")}
        local_images = getattr(args, "local_images", False)
        if local_images or contained:
            if not docker_ready():
                raise ValueError("Prepare Docker on the host before bootstrap")
        else:
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
        for img in dict.fromkeys([manager, candidate_image, executor]):
            check_image(img, pull=not local_images)
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
            "manager": manager,
            "candidate": candidate_image,
            "executor": executor,
            "docker_root": str(root),
            "containerd_root": str(containerd) if containerd else None,
            "temporary": str(temporary),
            "backup": str(backup),
        }
        if catalog is not None:
            config["release_catalog"] = catalog
        with tempfile.TemporaryDirectory(prefix=".bootstrap-partial-", dir=data) as folder:
            staging = Path(folder)
            for name, value in tls.items():
                atomic_write(staging / f"{name}.pem", value)
            if catalog_ca is not None:
                atomic_write(staging / "release-catalog-ca.pem", catalog_ca)
            if managed:
                atomic_write(staging / "host_bootstrap.py", launch_content)
                atomic_write(staging / LAUNCH_DIGEST, launch_digest.encode("ascii"))
                for name, mode in (("host-launch.sh", 0o700), ("launch-host.conf", 0o600)):
                    atomic_write(staging / name, launch_source.with_name(name).read_bytes(), mode)
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
        if not contained:
            install_unit(data, config)
        apply_manager(config, config["manager"], control / "bootstrap.compose.yaml")
    if getattr(args, "quiet", False):
        return
    print(f"Manager: https://localhost:{config['port']} (127.0.0.1)")
    print(f"Instance: {config['instance']} · {data} · {config['project']}")
    if managed:
        print_managed_access(data, config["port"])
    if not prior or args.new_pairing_token:
        if not sys.stdout.isatty():
            print(
                "Issue the pairing code from an administrative terminal using --new-pairing-token."
            )
        else:
            print("Enter this pairing code in the browser within 10 minutes:")
            print(init_container(config, "candidate-pair"))


def bootstrap_with_lock(args):
    import fcntl

    lock_dir = Path("/run/dvt-bootstrap")
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    safe_path(lock_dir)
    with (lock_dir / "bootstrap.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        bootstrap(args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "bootstrap", "resume", "maintenance", "maintenance-extend", "maintenance-defer",
            "cancel-preparation", "recover-manager", "return-to-source", "restore-start",
        ],
    )
    parser.add_argument("--operation-id")
    parser.add_argument("--dir", default="/var/lib/dvt")
    parser.add_argument("--project")
    parser.add_argument("--port", type=int)
    parser.add_argument("--public-url")
    parser.add_argument("--release-catalog-config", help="Trusted DVT catalog configuration JSON")
    parser.add_argument("--release-catalog-ca", help="PEM CA for the release catalog and its assets")
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
    for key in ("non-interactive", "install-docker", "new-pairing-token", "managed", "contained"):
        parser.add_argument(f"--{key}", action="store_true")
    args = parser.parse_args()
    try:
        os.umask(0o077)
        if os.geteuid() or not sys.platform.startswith("linux") or platform.machine() != "x86_64":
            raise ValueError("This candidate requires root on Linux amd64")
        if args.contained:
            if not HOST_OS_RELEASE.is_file() or (args.action == "bootstrap" and not args.managed):
                raise ValueError("Use the managed launcher with the host distribution bind mount")
        elif not Path("/run/systemd/system").is_dir():
            raise ValueError("The host must run systemd")
        if args.action != "bootstrap":
            config = load_host(safe_path(args.dir))
            operation = active_id(config)
            if args.action == "resume":
                if operation:
                    launch(config, operation)
                elif args.contained:
                    start_verified_manager(config)
            else:
                if not args.operation_id or args.operation_id != operation:
                    raise ValueError("Select the active update operation with --operation-id")
                if args.action == "restore-start":
                    from uuid import UUID

                    marker = safe_path(
                        Path(config["data"]) / STATE / "artifacts" / "staging" / str(UUID(operation))
                        / "restored-data.json"
                    )
                    if not marker.is_file():
                        raise ValueError("The selected operation has no prepared recovery data")
                    for key in ("temporary", "backup"):
                        safe_path(config[key]).mkdir(mode=0o700, parents=True, exist_ok=True)
                    if args.executor and args.executor != config["executor"]:
                        check_image(args.executor)
                        config = {**config, "executor": args.executor}
                        atomic_write(
                            Path(config["data"]) / CONTROL / "host.json", json.dumps(config).encode()
                        )
                    install_unit(Path(config["data"]), config)
                launch(config, operation, f"candidate-{args.action}")
        else:
            bootstrap_with_lock(args)
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
