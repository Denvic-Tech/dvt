"""Immutable, HTTPS-only release downloads through the executor's actual network path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..domain.operation_state import FailureReason
from ..domain.release_manifest import StagingError
from .staging_commands import Deadline, run_quietly


def classify_io_error(  # noqa: PLR0911 — diagnostic classes are ordered by specificity.
    reason: FailureReason,
    raw: bytes,
    *,
    return_code: int = 0,
    http_status: int = 0,
) -> StagingError:
    description = raw.lower()
    if b"no space left on device" in description or b"disk quota exceeded" in description:
        return StagingError(
            FailureReason.DISK_SPACE,
            "A write ran out of storage or quota",
            "Check space and free inodes on the actual Docker, containerd, or staging filesystem",
        )
    if return_code in (51, 58, 59, 60, 77, 83, 90, 91) or any(
        term in description
        for term in (
            b"x509:",
            b"certificate",
            b"unknown authority",
            b"https client",
        )
    ):
        return StagingError(
            FailureReason.TLS,
            "TLS certificate or trust validation failed",
            "Check the CA, server name, and clock used by the actual downloader",
        )
    if http_status in (401, 403) or any(
        term in description
        for term in (
            b"unauthorized",
            b"access denied",
            b"authentication required",
            b"denied:",
            b"401 unauthorized",
            b"403 forbidden",
        )
    ):
        return StagingError(
            reason, "Release endpoint denied access", "Check the endpoint's configured credentials"
        )
    if http_status == 404 or any(
        term in description for term in (b"manifest unknown", b"not found", b"no matching manifest")
    ):
        return StagingError(
            FailureReason.INVALID_PACKAGE,
            "The pinned artifact or platform is unavailable",
            "Verify that the exact release contents were delivered",
        )
    if return_code == 6 or any(
        term in description
        for term in (
            b"no such host",
            b"could not resolve host",
            b"name or service not known",
        )
    ):
        return StagingError(
            reason,
            "Release endpoint DNS resolution failed",
            "Check DNS in the affected downloader or Docker daemon network",
        )
    if (
        b"temporary failure in name resolution" in description
        or b"server misbehaving" in description
    ):
        return StagingError(
            reason,
            "Release endpoint returned a temporary DNS failure",
            "Check the resolver in the affected network",
            retryable=True,
        )
    if (
        return_code in (7, 18, 28, 52, 55, 56)
        or http_status in (408, 425, 429, 500, 502, 503, 504)
        or any(
            term in description
            for term in (
                b"connection reset",
                b"connection refused",
                b"unexpected eof",
                b"i/o timeout",
                b"tls handshake timeout",
                b"deadline exceeded",
                b"temporarily unavailable",
                b"too many requests",
                b"toomanyrequests",
                b"429",
                b"502 bad gateway",
                b"503 service unavailable",
                b"504 gateway timeout",
            )
        )
    ):
        return StagingError(
            reason,
            "Transient connection or upstream failure during release download",
            "Check endpoint availability, routing and path MTU from the actual downloader",
            retryable=True,
        )
    if return_code == 35 or b"tls:" in description or b"ssl" in description:
        return StagingError(
            FailureReason.TLS,
            "TLS negotiation failed",
            "Check the server TLS configuration and the executor or Docker daemon network path",
        )
    return StagingError(
        reason, "Release download failed", "Check the pinned endpoint and its HTTPS configuration"
    )


def https_origin(url: str) -> str:
    try:
        if any(char.isspace() or ord(char) < 32 or char in "\\?#" for char in url):
            raise ValueError
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None:
            raise ValueError
        port = parsed.port
        host = parsed.netloc.lower()
        if port == 443:
            host = host.removesuffix(":443")
    except ValueError:
        raise StagingError(
            FailureReason.INVALID_PACKAGE,
            "The artifact URL is invalid",
            "Supply a credential-free HTTPS URL for the pinned artifact",
        ) from None
    else:
        return f"https://{host}"


@dataclass(frozen=True)
class ReleaseDownloader:
    origins: frozenset[str]
    ca_file: Path | None = None

    def get(self, url: str, limit: int, *, cwd: Path, deadline: Deadline) -> bytes:
        if https_origin(url) not in self.origins:
            raise StagingError(
                FailureReason.INVALID_PACKAGE,
                "The artifact origin is outside the trust policy",
                "Use a release origin configured by bootstrap",
            )
        args = [
            "curl",
            "--disable",
            "--silent",
            "--show-error",
            "--fail",
            "--globoff",
            "--proto",
            "=https",
            "--noproxy",
            "*",
            "--max-filesize",
            str(limit),
            "--write-out",
            "%{http_code}",
        ]
        if self.ca_file is not None:
            args.extend(["--cacert", str(self.ca_file)])
        args.extend(["--url", url])
        reason = FailureReason.DISTRIBUTOR_UNAVAILABLE

        def download() -> bytes:
            result = run_quietly(args, deadline, reason, cwd=cwd, limit=limit + 8192)
            status = result.stdout[-3:]
            if result.code or status != b"200":
                if result.code == 63:
                    raise StagingError(
                        FailureReason.INVALID_PACKAGE,
                        "The release artifact exceeds its size limit",
                        "Check the artifact against the pinned manifest",
                    )
                raise classify_io_error(
                    reason,
                    result.stderr,
                    return_code=result.code,
                    http_status=int(status) if status.isdigit() else 0,
                )
            return result.stdout[:-3]

        return deadline.retry(download, reason)
