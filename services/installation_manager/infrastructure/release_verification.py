"""Pinned trust and integrity checks for online or cached release material."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..domain.operation_state import FailureReason, ReleasePin
from ..domain.release_manifest import (
    FileDescriptor,
    ReleaseManifest,
    SignedRelease,
    StagingError,
    canonical_json,
    digest_of,
    strict_json,
)

KEY_CONTEXT = b"DVT release signing key v1\0"
MANIFEST_CONTEXT = b"DVT release manifest v1\0"
MAX_MANIFEST_BYTES = 256 * 1024


@dataclass(frozen=True)
class TrustPolicy:
    # Bootstrap pins public roots and configures revoked key fingerprints out of band.
    roots: Mapping[str, bytes]
    revoked_signers: frozenset[str] = field(default_factory=frozenset)

    def as_document(self) -> dict:
        return {
            "roots": {name: value.hex() for name, value in self.roots.items()},
            "revoked_signers": sorted(self.revoked_signers),
        }

    @classmethod
    def from_document(cls, document: dict) -> Self:
        return cls(
            {name: bytes.fromhex(value) for name, value in document["roots"].items()},
            frozenset(document["revoked_signers"]),
        )

    def verify(
        self, content: bytes, pin: ReleasePin, *, now: datetime | None = None
    ) -> ReleaseManifest:
        if len(content) > MAX_MANIFEST_BYTES or digest_of(content) != pin.manifest_digest:
            raise invalid_package("The signed manifest does not match the pinned digest")

        try:
            envelope = SignedRelease.model_validate(strict_json(content))
            cert = envelope.signing_key
            manifest = envelope.payload
            root = Ed25519PublicKey.from_public_bytes(self.roots[cert.root_id])
            signer_bytes = bytes.fromhex(cert.public_key)
            if digest_of(signer_bytes) in self.revoked_signers:
                raise InvalidSignature
            signer = Ed25519PublicKey.from_public_bytes(signer_bytes)
            root.verify(
                bytes.fromhex(envelope.key_signature),
                KEY_CONTEXT + canonical_json(cert.model_dump(mode="json", by_alias=True)),
            )
            signer.verify(
                bytes.fromhex(envelope.manifest_signature),
                MANIFEST_CONTEXT + canonical_json(
                    manifest.model_dump(mode="json", by_alias=True, exclude_unset=True)
                ),
            )
            issued = datetime.fromisoformat(manifest.issued_at)
            expires = datetime.fromisoformat(manifest.expires_at)
            if not (
                datetime.fromisoformat(cert.valid_from)
                <= issued
                < expires
                <= datetime.fromisoformat(cert.valid_until)
                and issued <= (now or datetime.now(UTC)) < expires
            ):
                raise invalid_package("The release signature is outside its validity interval")
        except (InvalidSignature, KeyError, ValueError, RecursionError):
            raise invalid_package("The manifest format or release trust chain is invalid") from None
        if manifest.release_id != pin.release_id:
            raise invalid_package("The signed release identifier does not match the operation")
        return manifest


def invalid_package(problem: str) -> StagingError:
    return StagingError(
        FailureReason.INVALID_PACKAGE, problem, "Obtain the matching verified release package"
    )


def verify_file(content: bytes, descriptor: FileDescriptor, artifact: str) -> None:
    if len(content) != descriptor.size or digest_of(content) != descriptor.digest:
        raise invalid_package(f"The {artifact} artifact does not match the manifest")
