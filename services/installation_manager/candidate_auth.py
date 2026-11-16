"""Persistent authorization for the loopback HTTPS installation manager."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import ssl
import time
from pathlib import Path

from fastapi import HTTPException, Request

from .host_bootstrap import CONTROL, atomic_write
from .infrastructure.operation_files import _require_regular_file, executor_lock

PAIR_TTL = 600
SESSION_TTL = 8 * 3600


class CandidateAuth:
    def __init__(self, config: dict) -> None:
        self.directory = Path(config["data"]) / CONTROL
        self.origin = f"https://localhost:{config['port']}"
        self.host = f"localhost:{config['port']}"
        self.cookie = f"__Host-dvt-{config['instance']}"
        self.machine = self._read("machine-token").decode("ascii")
        self._key = self._read("session-key")

    def _read(self, name: str) -> bytes:
        path = self.directory / name
        _require_regular_file(path.lstat())
        return path.read_bytes()

    def probe_tls(self) -> ssl.SSLContext:
        # The same CA and server name are used from the host network and operator's tunnel.
        return ssl.create_default_context(cafile=self.directory / "ca.pem")

    def issue_pairing(self) -> str:
        token = secrets.token_urlsafe(32)
        with executor_lock(self.directory / "pairing.lock"):
            atomic_write(
                self.directory / "pairing.json",
                json.dumps(
                    {
                        "digest": hashlib.sha256(token.encode()).hexdigest(),
                        "expires": int(time.time()) + PAIR_TTL,
                    }
                ).encode(),
            )
        return token

    def pair(self, token: str) -> str:
        with executor_lock(self.directory / "pairing.lock"):
            try:
                pairing = json.loads(self._read("pairing.json"))
            except FileNotFoundError:
                raise HTTPException(401, "Invalid or expired pairing code") from None
            if pairing["expires"] <= time.time() or not hmac.compare_digest(
                pairing["digest"], hashlib.sha256(token.encode()).hexdigest()
            ):
                raise HTTPException(401, "Invalid or expired pairing code")
            # Persist consumption before issuing the session cookie.
            atomic_write(self.directory / "pairing.json", b'{"digest":"","expires":0}')
        payload = f"{int(time.time()) + SESSION_TTL}.{secrets.token_urlsafe(24)}"
        return f"{payload}.{self._signature(payload)}"

    def _signature(self, value: str) -> str:
        return hmac.new(self._key, value.encode(), hashlib.sha256).hexdigest()

    def _live_session(self, cookie: str) -> bool:
        try:
            expiry, _, signature = cookie.split(".")
            return (
                int(expiry) > time.time()
                and signature.isascii()
                and hmac.compare_digest(signature, self._signature(cookie.rpartition(".")[0]))
            )
        except ValueError:
            return False

    def csrf(self, request: Request) -> None:
        if (
            request.headers.get("origin") != self.origin
            or request.headers.get("x-dvt-csrf") != "1"
            or request.headers.get("content-type", "").split(";", 1)[0] != "application/json"
        ):
            raise HTTPException(403, "Origin or CSRF check failed")

    def require_operator(self, request: Request) -> None:
        origin = request.headers.get("origin")
        if origin is not None and origin != self.origin:
            raise HTTPException(403, "Origin is not authorized")
        authorization = request.headers.get("authorization")
        if authorization is not None:
            if (
                origin is not None
                or "sec-fetch-site" in request.headers
                or not authorization.isascii()
                or not hmac.compare_digest(authorization, f"Bearer {self.machine}")
            ):
                raise HTTPException(401, "Machine authorization required")
            return
        if not self._live_session(request.cookies.get(self.cookie, "")):
            raise HTTPException(401, "Pairing required")
        if request.method not in {"GET", "HEAD"}:
            self.csrf(request)
