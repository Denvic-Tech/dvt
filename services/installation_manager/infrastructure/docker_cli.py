"""Адаптер Docker: вызывает docker CLI, который через проброшенный
/var/run/docker.sock управляет Docker'ом хоста."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable

from ..domain.ports import CommandResult, DockerGateway
from ..logger import logger


class DockerCliGateway(DockerGateway):
    def run(
        self,
        args: list[str],
        input_text: str | None = None,
        timeout: int = 900,
    ) -> CommandResult:
        try:
            proc = subprocess.run(
                ["docker", *args],
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(124, f"docker {' '.join(args[:3])}... превысил таймаут {timeout}s")
        output = (proc.stdout or "").strip()
        if proc.stderr and proc.stderr.strip():
            output = f"{output}\n{proc.stderr.strip()}".strip()
        return CommandResult(proc.returncode, output)

    def run_streaming(
        self,
        args: list[str],
        on_line: Callable[[str], None],
        timeout: int = 3600,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        logger.info("Запуск: docker %s", " ".join(args))
        proc = subprocess.Popen(
            ["docker", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, **(env or {})},
            cwd=cwd,
        )
        lines: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            on_line(line)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = 124
            on_line(f"Таймаут {timeout}s, процесс остановлен")
        return CommandResult(code, "\n".join(lines))

    # ---- DockerGateway ----

    def docker_available(self) -> bool:
        return self.run(["version", "--format", "{{.Server.Version}}"], timeout=30).ok

    def compose_available(self) -> bool:
        return self.run(["compose", "version"], timeout=30).ok

    def system_id(self) -> str | None:
        res = self.run(["info", "--format", "{{.ID}}"], timeout=30)
        return res.output.strip() if res.ok and res.output.strip() else None

    def project_running(self, project_name: str, exclude_service: str = "") -> bool:
        res = self.run(
            [
                "ps",
                "--filter", f"label=com.docker.compose.project={project_name}",
                "--filter", "status=running",
                "--format", '{{.Label "com.docker.compose.service"}}',
            ],
            timeout=30,
        )
        if not res.ok:
            return False
        services = {line.strip() for line in res.output.splitlines() if line.strip()}
        services.discard(exclude_service)
        return bool(services)

    def login(self, registry: str, user: str, password: str) -> CommandResult:
        return self.run(
            ["login", registry, "-u", user, "--password-stdin"],
            input_text=password,
            timeout=120,
        )

    def ensure_network(self, name: str) -> CommandResult:
        if self.run(["network", "inspect", name], timeout=30).ok:
            return CommandResult(0, f"Сеть {name} уже существует")
        return self.run(["network", "create", name], timeout=60)

    def compose(
        self,
        project_name: str,
        compose_files: list[str],
        command: list[str],
        on_line: Callable[[str], None],
        env_file: str | None = None,
        project_dir: str | None = None,
    ) -> CommandResult:
        args: list[str] = ["compose"]
        if project_dir:
            args += ["--project-directory", project_dir]
        if project_name:
            args += ["--project-name", project_name]
        for f in compose_files:
            args += ["-f", f]
        if env_file:
            args += ["--env-file", env_file]
        args += command
        return self.run_streaming(
            args,
            on_line,
            timeout=3600,
            env={"DOCKER_BUILDKIT": "1", "COMPOSE_DOCKER_CLI_BUILD": "1"},
        )

    def diagnostics(self) -> str:
        parts: list[str] = []

        ps = self.run(
            ["ps", "-a", "--format", "table {{.Names}}\t{{.Status}}\t{{.Image}}"], timeout=60
        )
        parts.append("== Контейнеры ==\n" + ps.output)

        names = self.run(["ps", "-a", "--format", "{{.Names}}"], timeout=60).output.splitlines()
        if "dvt-valkey" in names:
            health = self.run(
                [
                    "inspect", "dvt-valkey", "--format",
                    "Status={{.State.Status}} "
                    "Health={{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}} "
                    "ExitCode={{.State.ExitCode}} Error={{.State.Error}}",
                ],
                timeout=60,
            )
            parts.append("== Valkey health ==\n" + health.output)
            logs = self.run(["logs", "--tail", "100", "dvt-valkey"], timeout=60)
            parts.append("== Valkey logs (tail 100) ==\n" + logs.output)

        for name in ("dvt-gateway", "dvt-proxy"):
            if name in names:
                logs = self.run(["logs", "--tail", "50", name], timeout=60)
                parts.append(f"== {name} logs (tail 50) ==\n" + logs.output)

        return "\n\n".join(parts)
