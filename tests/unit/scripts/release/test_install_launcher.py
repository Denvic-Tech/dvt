"""Exercise the POSIX launcher against isolated HTTPS with a Docker CLI fixture."""

import hashlib
import json
import os
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parents[4]
LAUNCHER = REPO / "install.sh"
BOOTSTRAP = REPO / "services/installation_manager/host_bootstrap.py"
MANAGER = "registry.fixture.test/dvt/installation_manager@sha256:" + "a" * 64
LOCAL_IMAGE = "dvt/installation_manager:latest"
LOCAL_MANAGER = "dvt/installation_manager@sha256:" + "d" * 64
LOCAL_UI_TAG = "dvt/ui:local-setup"
LOCAL_UI_PIN = "dvt/ui@sha256:" + "e" * 64

# Replace only the system Docker/systemd effects. The verified script still produces
# real TLS, persists the managed identity and uses the normal resume path.
HOST_FIXTURE = """
from types import SimpleNamespace

HOST_OS_RELEASE = Path("/etc/os-release")
# The real one-shot sees a private /run. This simulated container shares the
# host /run and the POSIX launcher already holds the host lock.
bootstrap_with_lock = bootstrap
check_port = lambda *args: None
check_project = lambda *args: None
docker_ready = lambda: True

def check_image(reference, **kwargs):
    assert reference in {"MANAGER_FIXTURE", "UI_FIXTURE"}
    if reference.startswith("dvt/"):
        assert not kwargs.get("pull", False)

def docker(*args, **kwargs):
    if args[0] == "info":
        return SimpleNamespace(stdout=json.dumps({"DockerRootDir": "ROOT_FIXTURE"}))
    witness = Path("DATA_FIXTURE") / "manager-witness"
    return SimpleNamespace(stdout="manager-is-running" if witness.exists() else "")

def apply_manager(config, image, path):
    assert config["manager"] == image == "MANAGER_FIXTURE"
    atomic_write(path, json.dumps(manager_compose(config, image)).encode())
    (Path(config["data"]) / "manager-witness").write_text(image)
def init_container(config, action):
    assert config["manager"] == "MANAGER_FIXTURE"
    if action == "candidate-init":
        key = Path(config["data"]) / CONTROL / "session-key"
        if not key.exists():
            atomic_write(key, b"s" * 32)
    if action == "candidate-pair":
        return "p" * 43
def active_id(config):
    sentinel = Path(config["data"]) / "pending-id"
    return sentinel.read_text() if sentinel.is_file() else None
def launch(config, operation):
    assert config["manager"] == "MANAGER_FIXTURE"
    (Path(config["data"]) / "resume-witness").write_text(operation)
""".replace("MANAGER_FIXTURE", MANAGER).replace("UI_FIXTURE", LOCAL_UI_PIN)


# The outer shell has no Python dependency. This isolated fixture adapts Docker
# run to the test venv and checks the one-shot execution boundary and mounts.
DOCKER_FIXTURE = r"""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

args = sys.argv[3:]
assert sys.argv[1:3] == ["--host", "unix:///var/run/docker.sock"]
if args[0] == "info":
    if args[1:] == ["--format", "{{.DockerRootDir}}"]:
        print(DOCKER_ROOT)
elif args[:2] == ["compose", "version"]:
    print("fixture")
elif args[:2] == ["compose", "--project-name"] and args[-1] == "down":
    pass
elif args[0] == "pull":
    assert args == ["pull", "--quiet", "--platform", "linux/amd64", MANAGER]
elif args[:2] == ["image", "inspect"]:
    print({LOCAL_IMAGE: LOCAL_MANAGER, LOCAL_UI_TAG: LOCAL_UI_PIN}[args[-1]])
elif args[0] == "run":
    manager = LOCAL_MANAGER if LOCAL_MANAGER in args else MANAGER
    boundary = args.index(manager)
    flags, container = args[1:boundary], args[boundary + 1:]
    assert "--rm" in flags and "--pull=never" in flags
    assert {"--privileged", "--pid=host"}.isdisjoint(flags)
    if container[:1] == ["-c"]:
        assert "WIZARD_PROTOCOL" in container[1]
        raise SystemExit(0)
    assert ("-t" in flags) == ("--non-interactive" not in container)
    assert flags[flags.index("--entrypoint") + 1] == "python3"
    mounts = [flags[index + 1] for index, value in enumerate(flags) if value == "--mount"]
    assert "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock" in mounts
    assert "type=bind,src=/etc/os-release,dst=/run/dvt-host-os,readonly" in mounts
    assert all(",src=/," not in mount for mount in mounts)
    assert "--contained" in container
    if manager == LOCAL_MANAGER:
        assert "com.docker.compose.project=" in flags
    with WITNESS.open("a", encoding="utf-8") as events:
        events.write(json.dumps(container[1:]) + "\n")
    for mount in mounts:
        if mount.endswith(",dst=/run/dvt-launch,readonly"):
            bootstrap_src = mount.split(",")[1].removeprefix("src=")
            container = [value.replace("/run/dvt-launch/", bootstrap_src + "/") for value in container]
    result = subprocess.call([sys.executable, "-I", *container])
    if result == 0 and "--wizard-source" in container and os.environ.get("DVT_FIXTURE_INTERRUPT"):
        os.kill(os.getppid(), signal.SIGKILL)
    raise SystemExit(result)
else:
    raise AssertionError(args)
"""


@unittest.skipUnless(
    sys.platform == "linux" and os.geteuid() == 0 and shutil.which("openssl")
    and Path("/run/dvt-launcher-test").is_file(),
    "Enable only in a disposable Linux container by creating /run/dvt-launcher-test",
)
class InstallLauncherTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir="/var/lib", prefix="dvt-launcher-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.data = self.root / "data"
        docker_root = self.root / "docker-storage"
        docker_root.mkdir()
        tls = self.root / "tls"
        tls.mkdir()
        # The signed release catalog still uses HTTPS independently of the manager UI.
        self.ca = tls / "cert.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-out", str(self.ca), "-keyout", str(tls / "key.pem"),
        ], check=True, capture_output=True)
        text = BOOTSTRAP.read_text(encoding="utf-8")
        tail = 'if __name__ == "__main__":'
        head, separator, call = text.rpartition(tail)
        self.assertTrue(separator)
        injected = HOST_FIXTURE.replace("ROOT_FIXTURE", str(docker_root))
        self.bootstrap = (head + injected.replace("DATA_FIXTURE", str(self.data))
                          + "\n" + separator + call).encode()
        self.assertFalse(Path("/usr/bin/python3").exists())
        self.events = self.root / "docker-events"
        self.project = "dvt-launch-fixture-" + self.root.name.rsplit("-", 1)[-1].lower()
        unit = Path("/etc/systemd/system") / f"dvt-bootstrap-{self.project}.service"
        self.addCleanup(unit.unlink, missing_ok=True)
        record = Path("/etc/dvt-bootstrap") / self.project
        self.addCleanup(record.unlink, missing_ok=True)
        definitions = (
            f"DOCKER_ROOT = {str(docker_root)!r}\nMANAGER = {MANAGER!r}\n"
            f"LOCAL_IMAGE = {LOCAL_IMAGE!r}\nLOCAL_MANAGER = {LOCAL_MANAGER!r}\n"
            f"LOCAL_UI_TAG = {LOCAL_UI_TAG!r}\nLOCAL_UI_PIN = {LOCAL_UI_PIN!r}\n"
            f"WITNESS = __import__('pathlib').Path({str(self.events)!r})\n"
        )
        for name, content in (
            ("docker", f"#!{sys.executable}\n" + definitions + DOCKER_FIXTURE),
            ("systemctl", "#!/bin/sh\nexit 0\n"),
        ):
            command = Path("/usr/local/bin") / name
            with command.open("x", encoding="utf-8") as stream:
                stream.write(content)
            self.addCleanup(command.unlink)
            command.chmod(0o700)
        self.received = []
        self.queries = []
        self.failure = None
        self.launcher = LAUNCHER

        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner):
                headers = {}
                location = urlsplit(inner.path)
                path = location.path
                if path == "/dvt/install.sh":
                    content = self.launcher.read_bytes()
                elif path == "/api/v1/dvt/releases/install":
                    self.received.append(path)
                    args = parse_qs(location.query)
                    self.queries.append(args)
                    if self.failure == "unavailable":
                        inner.send_error(503)
                        return
                    if self.failure == "not-ready":
                        inner.send_error(404)
                        return
                    assert args["channel"] == ["rc"]
                    assert args["platform"] == ["linux/amd64"]
                    asset = "/bootstrap.py"
                    if self.failure == "redirect":
                        asset = "/redirect.py"
                    assert inner.headers["Accept"] == "application/vnd.dvt.install+json"
                    descriptor = self.descriptor(asset)
                    bootstrap = descriptor["bootstrap"]
                    content = json.dumps(descriptor["catalog"]).encode()
                    headers = {
                        "X-DVT-Launch-Format": "1",
                        "X-DVT-Release-Version": descriptor["version"],
                        "X-DVT-Release-Channel": "rc",
                        "X-DVT-Manifest-Digest": descriptor["manifest_digest"],
                        "X-DVT-Catalog-Origin": self.origin,
                        "X-DVT-Catalog-Digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                        "X-DVT-Bootstrap-Origin": self.origin,
                        "X-DVT-Bootstrap-URL": bootstrap["url"],
                        "X-DVT-Bootstrap-Size": str(bootstrap["size"]),
                        "X-DVT-Bootstrap-Digest": bootstrap["digest"],
                        "X-DVT-Manager-Image": MANAGER,
                    }
                    if self.failure == "malformed":
                        del headers["X-DVT-Release-Version"]
                elif path == "/redirect.py":
                    inner.send_response(302)
                    inner.send_header("Location", self.origin + "/bootstrap.py")
                    inner.send_header("Content-Length", "0")
                    inner.end_headers()
                    return
                elif path == "/bootstrap.py":
                    self.received.append(path)
                    content = self.bootstrap
                    if self.failure == "corrupt":
                        content = bytes([content[0] ^ 1]) + content[1:]
                else:
                    inner.send_error(404)
                    return
                inner.send_response(200)
                inner.send_header("Content-Length", str(len(content)))
                for key, value in headers.items():
                    inner.send_header(key, value)
                inner.end_headers()
                inner.wfile.write(content)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"https://127.0.0.1:{self.server.server_port}"
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(tls / "cert.pem", tls / "key.pem")
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def descriptor(self, asset):
        return {
            "format_version": 1,
            "version": "1.24.0-rc4",
            "channel": "rc",
            "manifest_digest": "sha256:" + "c" * 64,
            "bootstrap": {
                "url": self.origin + asset,
                "size": len(self.bootstrap),
                "digest": "sha256:" + hashlib.sha256(self.bootstrap).hexdigest(),
            },
            "manager": MANAGER,
            "catalog": {
                "origin": self.origin,
                "trust": {"roots": {"fixture": "b" * 64}, "revoked_signers": []},
                "registry_hosts": ["registry.fixture.test"],
                "asset_origins": [self.origin],
            },
        }

    def launch_command(self, *flags, pass_ca=True, legacy_rc=True, wizard=False):
        command = 'bash <(curl -fsS --cacert "$1" "$2/dvt/install.sh") "${@:3}"'
        args = [
            "bash", "-c", command, "fixture", str(self.ca), self.origin,
            "--project", self.project, "--catalog-origin", self.origin, *flags,
        ]
        if not wizard:
            args.extend(("--non-interactive", "--dir", str(self.data), "--public-url", "https://dvt.fixture.test"))
        if legacy_rc:
            args.append("--test-rc")
        if pass_ca:
            args.extend(("--catalog-ca", str(self.ca)))
        return args

    def launch(self, *flags, **options):
        return subprocess.run(
            self.launch_command(*flags, **options),
            capture_output=True, text=True, check=False, timeout=40, start_new_session=True,
        )

    def test_wizard_creates_final_directory_after_submission_and_resumes_without_dir(self):
        self._exercise_wizard(
            self.launch_command("--new-pairing-token", wizard=True),
            self.launch_command("--non-interactive", wizard=True),
        )

    def test_local_image_wizard_without_systemd(self):
        launcher = self.local_launcher()
        systemd = Path("/run/systemd/system")
        systemd.rmdir()
        self.addCleanup(systemd.mkdir)
        command = [
            "sh", str(launcher), "--project", self.project, "--local-image", LOCAL_IMAGE,
            "--local-ui-image", LOCAL_UI_TAG, "--channel", "rc", "--catalog-origin", self.origin,
            "--catalog-ca", str(self.ca),
        ]
        self._exercise_wizard(
            [*command, "--new-pairing-token"], [*command, "--non-interactive"],
        )

    def test_wizard_resumes_after_interrupted_handoff(self):
        self._exercise_wizard(
            self.launch_command("--new-pairing-token", wizard=True),
            self.launch_command("--non-interactive", wizard=True),
            interrupt=True,
        )

    @unittest.skipUnless(socket.has_ipv6, "An IPv6 socket is required")
    def test_wizard_publishes_ipv6_for_an_ipv6_ssh_connection(self):
        self._exercise_wizard(
            self.launch_command("--new-pairing-token", wizard=True),
            self.launch_command("--non-interactive", wizard=True),
            ipv6=True,
        )

    def _exercise_wizard(self, launch, repeat, *, interrupt=False, ipv6=False):
        bind = "::" if ipv6 else "0.0.0.0"
        detected = "2001:db8::20" if ipv6 else "192.0.2.20"
        authority = f"[{detected}]" if ipv6 else detected
        family = socket.AF_INET6 if ipv6 else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as busy:
            try:
                busy.bind((bind, 8888))
            except OSError:
                pass  # An existing listener already occupies the preferred port.
            else:
                busy.listen()
            env = {**os.environ, "SSH_CONNECTION": f"192.0.2.2 12000 {detected} 22"}
            if interrupt:
                env["DVT_FIXTURE_INTERRUPT"] = "1"
            with subprocess.Popen(
                launch,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                start_new_session=True,
            ) as process:
                try:
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        if self.events.exists() and self.events.read_text().strip():
                            call = json.loads(self.events.read_text().splitlines()[0])
                            control = Path(call[call.index("--dir") + 1]) / ".bootstrap"
                            if (control / "host.json").is_file():
                                break
                        if process.poll() is not None:
                            self.fail(process.communicate())
                        time.sleep(0.05)
                    else:
                        self.fail("The temporary manager did not start")
                    temporary = json.loads((control / "host.json").read_bytes())
                    self.assertFalse(self.data.exists())
                    self.assertNotEqual(temporary["port"], 8888)
                    self.assertTrue(temporary["wizard_temporary"])
                    self.assertEqual(temporary["address"], bind)
                    self.assertEqual(temporary["public_url"], f"http://{authority}")
                    request = {
                        "key": "install-intent",
                        "request": {
                            "kind": "install", "install_dir": str(self.data),
                            "public_urls": ["http://app.example:9999"],
                        },
                    }
                    self.write_intent(control, {
                        "key": "unsafe-install-intent",
                        "request": {**request["request"], "install_dir": "/run/dvt-fixture"},
                    })
                    deadline = time.monotonic() + 10
                    error = control / "install-error.json"
                    while not error.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertEqual(json.loads(error.read_bytes())["key"], "unsafe-install-intent")
                    self.assertFalse(Path("/run/dvt-fixture").exists())
                    self.write_intent(control, request)
                    stdout, stderr = process.communicate(timeout=40)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.communicate(timeout=10)
        if interrupt:
            self.assertNotEqual(process.returncode, 0)
            self.assertTrue(control.exists())
            self.assertFalse((self.data / "manager-witness").exists())
        else:
            self.assertEqual(process.returncode, 0, stdout + stderr)
        self.received.clear()
        repeat_in_terminal = shlex.join(arg for arg in repeat if arg != "--non-interactive")
        resumed = subprocess.run(
            ["script", "-qec", repeat_in_terminal, "/dev/null"],
            capture_output=True, text=True, timeout=40, check=False,
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(self.received, [])
        self.assertTrue((self.data / "manager-witness").exists())
        final = self.data / ".bootstrap"
        config = json.loads((final / "host.json").read_bytes())
        self.assertEqual(config["instance"], temporary["instance"])
        self.assertEqual(config["manager_origins"], temporary["manager_origins"])
        self.assertEqual(config["public_url"], "http://app.example:9999")
        self.assertEqual((final / "session-key").read_bytes(), b"s" * 32)
        self.assertEqual(json.loads((final / "install-intent.json").read_bytes()), request)
        self.assertFalse(control.exists())
        self.assertEqual(config["address"], bind)
        for host in ("localhost", authority):
            link = f"http://{host}:{config['port']}/#pairing=" + "p" * 43
            self.assertIn(link, stdout)
            self.assertIn(link, resumed.stdout)

    @staticmethod
    def write_intent(control, request):
        staged = control / ".intent.new"
        staged.write_text(json.dumps(request))
        staged.replace(control / "install-intent.json")

    def local_launcher(self):
        local_bootstrap = self.root / "services/installation_manager/host_bootstrap.py"
        local_bootstrap.parent.mkdir(parents=True)
        local_bootstrap.write_bytes(self.bootstrap.replace(MANAGER.encode(), LOCAL_MANAGER.encode()))
        launcher = self.root / "install.sh"
        shutil.copyfile(LAUNCHER, launcher)
        return launcher

    def test_local_image_uses_local_bootstrap_without_systemd(self):
        launcher = self.local_launcher()
        systemd = Path("/run/systemd/system")
        systemd.rmdir()
        self.addCleanup(systemd.mkdir)

        result = subprocess.run(
            [
                "sh", str(launcher), "--local-image", LOCAL_IMAGE,
                "--local-ui-image", LOCAL_UI_TAG, "--dir", str(self.data), "--public-url", "http://localhost",
                "--non-interactive", "--channel", "rc",
                "--catalog-origin", self.origin, "--catalog-ca", str(self.ca),
            ],
            check=False, capture_output=True, text=True, timeout=40,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.data / "manager-witness").read_text(), LOCAL_MANAGER)
        self.assertNotIn("Downloading the installation manager", result.stdout)
        self.assertNotIn("/bootstrap.py", self.received)
        config = json.loads((self.data / ".bootstrap" / "host.json").read_bytes())
        self.assertEqual(config["release_catalog"]["origin"], self.origin)
        self.assertEqual(config["project"], "dvt-local")
        self.assertEqual(config["address"], "0.0.0.0")
        self.assertEqual(config["local_ui_image"], LOCAL_UI_PIN)

    def test_explicit_channel_pins_release_and_resume_checks_saved_version(self):
        result = self.launch("--channel", "rc", legacy_rc=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.queries[0]["channel"], ["rc"])
        self.assertNotIn("version", self.queries[0])
        pin = (self.data / ".bootstrap" / "launch-host.conf").read_text().splitlines()[5]
        self.assertEqual(pin, "1.24.0-rc4 " + self.descriptor("/bootstrap.py")["manifest_digest"])
        self.received.clear()
        same = self.launch("--version", "1.24.0-rc4", legacy_rc=False)
        self.assertEqual(same.returncode, 0, same.stderr)
        other = self.launch("--version", "1.24.0-rc5", legacy_rc=False)
        self.assertNotEqual(other.returncode, 0)
        self.assertIn("different release selection", other.stderr)
        self.assertEqual(self.received, [])

    def test_exact_version_rejects_substitution_before_fetching_bootstrap(self):
        wrong = self.launch("--version", "1.24.0-rc8", legacy_rc=False)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn("instead of requested version 1.24.0-rc8", wrong.stderr)
        self.assertNotIn("/bootstrap.py", self.received)
        self.assertEqual(self.queries[0]["version"], ["1.24.0-rc8"])
        self.assertEqual(self.queries[0]["channel"], ["rc"])
        good = self.launch("--version", "1.24.0-rc4", legacy_rc=False)
        self.assertEqual(good.returncode, 0, good.stderr)

    def launcher_with_os_release(self, os_release, content=None):
        if content is not None:
            os_release.write_text(content)
        self.launcher = self.root / "install.sh"
        self.launcher.write_text(
            LAUNCHER.read_text(encoding="utf-8")
            .replace("host_os_release=/etc/os-release", f"host_os_release={os_release}")
            .replace("host_os_release=/usr/lib/os-release", f"host_os_release={os_release}"),
            encoding="utf-8",
        )

    def test_unlisted_host_installs_through_catalog(self):
        self.launcher_with_os_release(
            self.root / "os-release", 'ID=debian\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\n',
        )

        result = self.launch()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.queries[0]["distribution"], ["debian"])
        self.assertEqual(self.queries[0]["distribution_version"], ["12"])
        self.assertEqual((self.data / "manager-witness").read_text(), MANAGER)

    def test_install_catalog_query_without_os_release(self):
        self.launcher_with_os_release(self.root / "missing-os-release")

        result = self.launch()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("distribution", self.queries[0])
        self.assertNotIn("distribution_version", self.queries[0])

    def test_default_requests_only_stable_and_conflicts_fail_locally(self):
        self.failure = "not-ready"
        result = self.launch(legacy_rc=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("(stable)", result.stderr)
        self.assertEqual([query["channel"] for query in self.queries], [["stable"]])
        result = self.launch("--channel", "stable", "--version", "1.24.0-rc8", legacy_rc=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Version and channel disagree", result.stderr)
        self.assertEqual(len(self.queries), 1)

    def test_verifies_the_configuration_then_reuses_the_same_identity(self):
        fresh = self.launch()
        self.assertEqual(fresh.returncode, 0, fresh.stdout + fresh.stderr)
        self.assertIn("Manager: http://dvt.fixture.test:8888", fresh.stdout)
        self.assertNotIn("#pairing=", fresh.stdout)
        control = self.data / ".bootstrap"
        config = json.loads((control / "host.json").read_bytes())
        self.assertEqual(config["manager"], MANAGER)
        self.assertEqual(config["public_url"], "https://dvt.fixture.test")
        policy = config["release_catalog"]
        self.assertEqual(policy["origin"], self.origin)
        self.assertEqual(policy["trust"], self.descriptor("/bootstrap.py")["catalog"]["trust"])
        self.assertEqual((control / "release-catalog-ca.pem").read_bytes(), self.ca.read_bytes())
        self.assertEqual((self.data / "manager-witness").read_text(), MANAGER)
        paths = ("host.json", "host_bootstrap.py", "launch-bootstrap.sha256", "current-manager",
                 "host-launch.sh", "launch-host.conf", "release-catalog-ca.pem")
        old = {name: (control / name).read_bytes() for name in paths}
        for name in ("ca.pem", "key.pem", "cert.pem"):
            self.assertFalse((control / name).exists())
        (self.data / "pending-id").write_text("pending-operation-fixture")
        self.failure = "unavailable"
        self.received.clear()

        repeat = self.launch(pass_ca=False)
        self.assertEqual(repeat.returncode, 0, repeat.stdout + repeat.stderr)
        self.assertEqual(self.received, [])
        resumed = subprocess.run(
            ["/bin/dash", str(control / "host-launch.sh"), "resume", str(self.data)],
            capture_output=True, text=True, check=False,
            timeout=40, start_new_session=True,
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        calls = [json.loads(line) for line in self.events.read_text().splitlines()]
        self.assertEqual([args[0] for args in calls], ["bootstrap", "bootstrap", "resume"])
        self.assertEqual((self.data / "resume-witness").read_text(), "pending-operation-fixture")
        self.assertEqual({name: (control / name).read_bytes() for name in paths}, old)
        (self.data / "pending-id").unlink()
        (self.data / "manager-witness").unlink()
        reboot = subprocess.run(
            ["/bin/dash", str(control / "host-launch.sh"), "resume", str(self.data)],
            capture_output=True, text=True, check=False, timeout=40, start_new_session=True,
        )
        self.assertEqual(reboot.returncode, 0, reboot.stderr)
        self.assertEqual((self.data / "manager-witness").read_text(), MANAGER)

        (control / "host_bootstrap.py").write_bytes(old["host_bootstrap.py"] + b"\n")
        tampered = self.launch(pass_ca=False)
        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn("saved managed bootstrap failed its digest check", tampered.stderr)
        self.assertEqual(self.received, [])

    def test_refuses_unavailable_unapproved_corrupt_redirected_and_untrusted_delivery(self):
        for error, expected in (
            ("unavailable", "HTTPS catalog/certificate is unavailable"),
            ("not-ready", "No approved initial release"),
            ("corrupt", "failed its signed size or digest check"),
            ("redirect", "failed its signed size or digest check"),
            ("malformed", "Invalid installation descriptor"),
            ("untrusted", "HTTPS catalog/certificate is unavailable"),
        ):
            with self.subTest(error=error):
                self.failure = error
                self.received.clear()
                result = self.launch(pass_ca=error != "untrusted")
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(expected, result.stderr)
                self.assertFalse(self.data.exists())
                if error != "corrupt":
                    self.assertNotIn("/bootstrap.py", self.received)
