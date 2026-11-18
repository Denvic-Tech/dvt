"""Resolve exact Linux amd64 leaf images and measure their layer footprints."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

from services.installation_manager.domain.operation_state import ReleasePin
from services.installation_manager.domain.release_manifest import (
    ImageDescriptor,
    SignedRelease,
    canonical_json,
    digest_of,
    strict_json,
)
from services.installation_manager.infrastructure.release_verification import (
    MAX_MANIFEST_BYTES,
    TrustPolicy,
)

from .build_manifest import COMPOSE, git, load_compose, source_repository, write_once

PRODUCT_ROLES = (
    "orchestrator", "task-worker", "project-scheduler", "gateway", "dvt-ai-mcp",
    "installation_manager", "ui", "proxy",
)
INFRASTRUCTURE_ROLES = {"postgres", "valkey"}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
DEFAULT_TAG = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:-([^{}]*)\}")


def skopeo(*args: str) -> bytes:
    command = ["skopeo", "--override-os", "linux", "--override-arch", "amd64", *args]
    return subprocess.run(command, capture_output=True, check=True, timeout=3600).stdout


def split_ref(reference: str) -> tuple[str, str]:
    if not isinstance(reference, str):
        raise TypeError("An image reference must be a string")
    repository, separator, digest = reference.rpartition("@")
    if separator:
        if not DIGEST.fullmatch(digest):
            raise ValueError("Invalid input digest")
        return repository, digest
    repository, separator, tag = reference.rpartition(":")
    if not separator or "/" in tag or not tag:
        raise ValueError("A tag or digest is required")
    return repository, ""


def leaf_reference(reference: str, auth: str) -> str:
    repository, expected_digest = split_ref(reference)
    raw = skopeo("inspect", "--raw", "--authfile", auth, f"docker://{reference}")
    document = json.loads(raw)
    actual_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if expected_digest and expected_digest != actual_digest:
        raise ValueError("The Registry manifest differs from the BuildKit digest")
    if "manifests" not in document:
        return f"{repository}@{actual_digest}"
    linux_amd64 = [
        item["digest"] for item in document["manifests"]
        if item.get("platform", {}).get("os") == "linux"
        and item.get("platform", {}).get("architecture") == "amd64"
        and not item["platform"].get("variant")
    ]
    if len(linux_amd64) != 1 or not DIGEST.fullmatch(linux_amd64[0]):
        raise ValueError("Expected exactly one generic Linux amd64 image")
    return f"{repository}@{linux_amd64[0]}"


def layer_budget(path: Path) -> tuple[int, int]:
    """Conservative additive estimate with a 4 KiB allocation per directory entry."""
    size = inodes = 0
    with tarfile.open(path, mode="r|*") as layer:
        for entry in layer:
            inodes += 1
            size += 4096 + ((entry.size + 4095) // 4096) * 4096
    return size, inodes


def measure(reference: str, auth: str, directory: Path) -> tuple[int, int, int]:
    skopeo(
        "copy", "--preserve-digests", "--src-authfile", auth,
        f"docker://{reference}", f"dir:{directory}",
    )
    raw = (directory / "manifest.json").read_bytes()
    _, digest = split_ref(reference)
    if digest != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise ValueError("The copied leaf differs from the locked digest")
    manifest = json.loads(raw)
    if manifest["schemaVersion"] != 2 or not manifest["layers"]:
        raise ValueError("Expected an OCI or Docker v2 image")
    config = manifest["config"]
    compressed = len(raw)
    for descriptor in (config, *manifest["layers"]):
        blob = descriptor["digest"]
        if not DIGEST.fullmatch(blob) or descriptor.keys() & {"urls", "data"}:
            raise ValueError("External or invalid image blob")
        path = directory / blob.removeprefix("sha256:")
        with path.open("rb") as stream:
            if (
                path.stat().st_size != descriptor["size"]
                or hashlib.file_digest(stream, "sha256").hexdigest() != blob.removeprefix("sha256:")
            ):
                raise ValueError("A Registry blob differs from its signed descriptor")
        compressed += descriptor["size"]
    platform = json.loads((directory / config["digest"].removeprefix("sha256:")).read_bytes())
    if (platform.get("os"), platform.get("architecture")) != ("linux", "amd64"):
        raise ValueError("The image is outside the Linux amd64 profile")
    budgets = [
        layer_budget(directory / item["digest"].removeprefix("sha256:"))
        for item in manifest["layers"]
    ]
    return compressed, sum(size for size, _ in budgets), sum(count for _, count in budgets)


def previous_budgets(
    manifest_path: Path | None, trust_path: Path | None,
) -> dict[str, tuple[int, int, int]]:
    """Treat the optional CI cache as untrusted until its signed envelope is verified."""
    if manifest_path is None:
        return {}
    try:
        if trust_path is None:
            raise ValueError("No trust policy")
        with manifest_path.open("rb") as stream:
            content = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(content) > MAX_MANIFEST_BYTES:
            raise ValueError("Manifest too large")
        with trust_path.open("rb") as stream:
            policy = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(policy) > MAX_MANIFEST_BYTES:
            raise ValueError("Trust policy too large")
        document = strict_json(policy)
        if (
            not isinstance(document, dict) or set(document) != {"roots", "revoked_signers"}
            or not isinstance(document["roots"], dict) or not document["roots"]
            or any(
                not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
                for key in document["roots"].values()
            )
            or not isinstance(document["revoked_signers"], list)
            or any(
                not isinstance(key, str) or not DIGEST.fullmatch(key)
                for key in document["revoked_signers"]
            )
        ):
            raise ValueError("Invalid trust policy")
        envelope = SignedRelease.model_validate(strict_json(content))
        manifest = TrustPolicy.from_document(document).verify(
            content, ReleasePin(envelope.payload.release_id, digest_of(content)),
        )
        platform = manifest.platforms.get("linux/amd64")
        budgets = {}
        for image in platform.images.values() if platform else ():
            _, digest = split_ref(image.reference)
            values = image.compressed_bytes, image.unpacked_bytes, image.unpacked_inodes
            if budgets.setdefault(digest, values) != values:
                raise ValueError("Conflicting signed budgets for one leaf")
    except (OSError, KeyError, ValueError, TypeError, RuntimeError, RecursionError):
        # Never expose certificate/input details or allow a damaged cache to block a release.
        print("Previous image budgets unavailable or untrusted; measuring images", file=sys.stderr)
        return {}
    return budgets


def build_inventory(args: argparse.Namespace, auth: str) -> dict[str, dict]:
    if args.references:
        if args.infrastructure:
            raise ValueError("--infrastructure requires BuildKit metadata mode")
        inputs = json.loads(args.references.read_bytes())
        if not isinstance(inputs, dict) or inputs.get("migrate") != inputs.get("gateway"):
            raise ValueError("Expected a service map with identical Gateway and migration references")
        input_refs = {role: (reference, "") for role, reference in inputs.items()}
    else:
        if not args.upstream or not args.integration_lock:
            raise ValueError("BuildKit mode requires --upstream and --integration-lock")
        metadata = json.loads(args.metadata.read_bytes())
        infrastructure = json.loads(args.infrastructure.read_bytes()) if args.infrastructure else {}
        if args.infrastructure and (
            not isinstance(infrastructure, dict) or infrastructure.keys() != INFRASTRUCTURE_ROLES
        ):
            raise ValueError("Provide both approved PostgreSQL and Valkey references")
        compose = load_compose(git(args.source, "show", "HEAD:" + COMPOSE))
        input_refs = {}
        for role, service in compose["services"].items():
            source = service["image"]
            public_repository = source_repository(source)
            image = "gateway" if role == "migrate" else role
            if image in PRODUCT_ROLES:
                digest = metadata[image]["containerimage.digest"]
                if not DIGEST.fullmatch(digest):
                    raise ValueError("An image has no immutable BuildKit result")
                ref = f"{args.upstream.rstrip('/')}/{image}@{digest}"
            elif role in infrastructure:
                ref = infrastructure[role]
                repository, digest = split_ref(ref)
                if not digest or repository != public_repository:
                    raise ValueError(f"Provide the approved infrastructure repository and digest for {role}")
            else:
                tag = DEFAULT_TAG.sub(lambda match: match[1], source).rsplit(":", 1)[1]
                ref = f"{public_repository}:{tag}"
            input_refs[role] = ref, public_repository

    inventory = {}
    measured = {}
    budgets = previous_budgets(
        getattr(args, "previous_manifest", None), getattr(args, "trust", None),
    )
    for role, (reference, public_repository) in input_refs.items():
        if reference not in measured:
            leaf = leaf_reference(reference, auth)
            if args.infrastructure and role in INFRASTRUCTURE_ROLES and leaf != reference:
                raise ValueError(f"Expected the exact predecessor image leaf for {role}")
            repository, digest = split_ref(leaf)
            if digest not in budgets:
                with TemporaryDirectory(prefix="dvt-layer-", dir=args.scratch) as directory:
                    budgets[digest] = measure(leaf, auth, Path(directory))
            compressed, unpacked, inodes = budgets[digest]
            measured[reference] = ImageDescriptor(
                reference=f"{public_repository or repository}@{digest}",
                compressed_bytes=compressed,
                unpacked_bytes=unpacked,
                unpacked_inodes=inodes,
            ).model_dump()
        inventory[role] = measured[reference]
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--metadata", type=Path, help="BuildKit bake --metadata-file output")
    mode.add_argument("--references", type=Path, help="Private test registry references per role")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--previous-manifest", type=Path,
        help="Optional cached signed release envelope; invalid or stale cache is remeasured",
    )
    parser.add_argument(
        "--trust", type=Path,
        help="Approved release trust policy, required to reuse --previous-manifest budgets",
    )
    parser.add_argument("--source", default=Path(), type=Path)
    parser.add_argument("--auth-file", type=Path)
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--upstream", help="Build registry image prefix, including /dvt")
    parser.add_argument("--integration-lock", type=Path)
    parser.add_argument("--infrastructure", type=Path, help="Approved predecessor PostgreSQL/Valkey digests")
    args = parser.parse_args()
    try:
        with TemporaryDirectory(prefix="dvt-registry-auth-") as directory:
            auth = args.auth_file or Path(directory) / "auth.json"
            if args.auth_file is None:
                auth.write_text('{"auths":{}}', encoding="utf-8")
            inventory = build_inventory(args, str(auth))
        write_once(args.output, canonical_json(inventory))
        if args.integration_lock:
            values = [f"DVT_CANDIDATE_IMAGES='{' '.join(PRODUCT_ROLES)}'"]
            for role in PRODUCT_ROLES:
                env_key = role.upper().replace("-", "_")
                digest = inventory[role]["reference"].rsplit("@", 1)[1]
                values.append(f"DVT_CANDIDATE_DIGEST_{env_key}={digest}")
            write_once(args.integration_lock, ("\n".join(values) + "\n").encode())
    except (OSError, KeyError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError,
            tarfile.TarError, RecursionError):
        print("Could not resolve all exact Linux amd64 release images and layer budgets", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
