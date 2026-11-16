from __future__ import annotations

import io
import tarfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.data.installation_manager.verified_staging.fixtures import (
    BOOTSTRAP,
    ROOT,
    SIGNER,
    make_compose,
    make_manifest,
    sign_manifest,
)

from services.installation_manager.domain.operation_state import FailureReason
from services.installation_manager.domain.release_manifest import (
    StagingError,
    canonical_json,
    digest_of,
)
from services.installation_manager.infrastructure.offline_bundle import (
    OFFLINE_CONTEXT,
    extract_bundle,
    image_alias,
    inspect_oci,
)
from services.installation_manager.infrastructure.offline_host import (
    check_bundle_host,
    import_offline_images,
)
from services.installation_manager.infrastructure.release_verification import TrustPolicy
from services.installation_manager.infrastructure.staging_docker import StagingDocker

TRUST = TrustPolicy({"beta-root": ROOT.public_key().public_bytes_raw()})
MEDIA = "application/vnd.oci.image.manifest.v1+json"


def _add(tar: tarfile.TarFile, name: str, contents: bytes) -> None:
    item = tarfile.TarInfo(name)
    item.size = len(contents)
    tar.addfile(item, io.BytesIO(contents))


def _oci(tag: str | None = None) -> tuple[str, bytes, str, list[str]]:
    layer = b"layer bytes"
    diff = [digest_of(layer)]
    config = canonical_json({
        "os": "linux", "architecture": "amd64", "rootfs": {"type": "layers", "diff_ids": diff},
    })
    manifest = canonical_json({
        "schemaVersion": 2,
        "mediaType": MEDIA,
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": digest_of(config), "size": len(config),
        },
        "layers": [{
            "mediaType": "application/vnd.oci.image.layer.v1.tar",
            "digest": digest_of(layer), "size": len(layer),
        }],
    })
    reference = "registry.invalid/dvt/image@" + digest_of(manifest)
    alias = image_alias(reference)
    index = canonical_json({
        "schemaVersion": 2,
        "manifests": [{
            "mediaType": MEDIA, "digest": digest_of(manifest), "size": len(manifest),
            "platform": {"os": "linux", "architecture": "amd64"},
            "annotations": {
                "io.containerd.image.name": tag or alias,
                "org.opencontainers.image.ref.name": alias.rsplit(":", 1)[1],
            },
        }],
    })
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        _add(tar, "index.json", index)
        _add(tar, "oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
        for blob in (manifest, config, layer):
            _add(tar, "blobs/sha256/" + digest_of(blob).split(":")[1], blob)
    return reference, buffer.getvalue(), digest_of(config), diff


def _archive(tmp_path: Path, defect: str | None = None):
    source = tmp_path / "fixture.tar.gz"
    reference, image, config, diff = _oci("registry.invalid/dvt/image:latest" if defect == "alias" else None)
    path = "images/" + digest_of(reference.encode()).split(":")[1] + ".tar"
    compose = make_compose(reference)
    pin, signed = sign_manifest(make_manifest(compose, reference=reference, infrastructure=reference))
    payload = {
        "compose.yaml": compose,
        "bootstrap.sh": BOOTSTRAP,
        "install.sh": b"fixture",
        "update.sh": b"fixture",
        path: image,
    }
    index = canonical_json({
        "format_version": 1,
        "root_id": "beta-root",
        "release_id": pin.release_id,
        "manifest_digest": pin.manifest_digest if defect != "pin" else digest_of(b"different"),
        "kind": "update",
        "platform": "linux/amd64",
        "distribution": "debian",
        "distribution_version": "12" if defect == "distribution" else "13",
        "profiles": [],
        "extensions": [],
        "images": {reference: path} if defect != "incomplete-images" else {},
        "files": {
            name: {"size": len(content), "digest": digest_of(content)}
            for name, content in payload.items()
        },
    })
    signature = SIGNER.sign(OFFLINE_CONTEXT + index).hex().encode()
    if defect == "signature":
        signature = b"0" * 128
    with tarfile.open(source, "w:gz", format=tarfile.USTAR_FORMAT) as tar:
        _add(tar, "bundle.json", index)
        _add(tar, "bundle.sig", signature)
        _add(tar, "manifest.json", signed)
        for name, content in payload.items():
            if name == path and defect == "missing-member":
                continue
            data = b"x" + content[1:] if name == path and defect == "changed-member" else content
            _add(tar, name, data)
        if defect == "traversal":
            _add(tar, "../outside", b"escape")
        if defect == "duplicate":
            _add(tar, "compose.yaml", compose)
        if defect in {"symlink", "hardlink"}:
            item = tarfile.TarInfo("extensions/unsafe")
            item.type = tarfile.SYMTYPE if defect == "symlink" else tarfile.LNKTYPE
            item.linkname = "/etc/passwd"
            tar.addfile(item)
    directory = tmp_path / "extract"
    directory.mkdir(mode=0o700)
    return source, directory, reference, path, config, diff


@pytest.mark.parametrize(
    "defect",
    ("signature", "pin", "distribution", "incomplete-images", "missing-member",
     "changed-member", "traversal", "duplicate", "symlink", "hardlink"),
)
def test_offline_archive_rejects_invalid_inputs(tmp_path, defect) -> None:
    source, directory, *_ = _archive(tmp_path, defect)
    with pytest.raises(StagingError) as error:
        extract_bundle(source, directory, TRUST)
    assert error.value.reason is FailureReason.INVALID_PACKAGE
    assert not (tmp_path / "outside").exists()


def test_offline_archive_preserves_exact_oci_leaf_and_rechecks_host(tmp_path) -> None:
    source, target, reference, name, config, diff = _archive(tmp_path)
    bundle = extract_bundle(source, target, TRUST)
    assert inspect_oci(target / name, reference, "linux/amd64") == (config, diff)
    os_release = tmp_path / "os-release"
    os_release.write_text('ID=debian\nVERSION_ID="13"\n', encoding="utf-8")
    check_bundle_host(bundle, os_release, (), "linux/amd64")
    with pytest.raises(StagingError, match="different host or Compose profile"):
        check_bundle_host(bundle, os_release, ("ai-mcp",), "linux/amd64")
    revoked = replace(
        TRUST, revoked_signers=frozenset({digest_of(SIGNER.public_key().public_bytes_raw())}),
    )
    with pytest.raises(StagingError, match="trust chain"):
        extract_bundle(source, target, revoked)


def test_oci_local_image_id_and_layers_are_verified_after_load(tmp_path) -> None:
    source, target, reference, name, _, diff = _archive(tmp_path)
    bundle = extract_bundle(source, target, TRUST)
    loaded = []
    leaf = reference.split("@")[1]
    observed = {"Id": leaf, "Descriptor": {"digest": leaf}, "RootFS": {"Layers": diff}}
    docker = SimpleNamespace(
        local_image=lambda ref, platform, deadline: bool(loaded),
        load_image=lambda archive, deadline: loaded.append(archive),
        inspect_image=lambda ref, deadline: observed,
    )
    import_offline_images(bundle, docker, None)
    assert loaded == [target / name]
    observed["RootFS"]["Layers"] = [digest_of(b"another layer")]
    with pytest.raises(StagingError, match="image identity"):
        import_offline_images(bundle, docker, None)
    assert loaded == [target / name]


def test_oci_alias_tamper_is_rejected_before_loading(tmp_path) -> None:
    source, target, reference, name, _, _ = _archive(tmp_path, "alias")
    extract_bundle(source, target, TRUST)
    with pytest.raises(StagingError):
        inspect_oci(target / name, reference, "linux/amd64")


def test_offline_preparer_requires_a_compatible_local_executor(tmp_path, monkeypatch) -> None:
    reference, *_ = _oci()
    commands = []
    monkeypatch.setattr(StagingDocker, "local_image", lambda *_: True)

    def old_executor(_, args, deadline, **_options):
        commands.append(args)
        return SimpleNamespace(code=1)

    monkeypatch.setattr(StagingDocker, "_run", old_executor)
    docker = StagingDocker(tmp_path, tmp_path)
    with pytest.raises(StagingError, match="executor cannot apply offline"):
        docker.check_offline_executor(reference, None)
    assert len(commands) == 1
    assert reference in commands[0]
    assert "--pull=never" in commands[0] and "--network=none" in commands[0]

    monkeypatch.setattr(StagingDocker, "local_image", lambda *_: False)
    with pytest.raises(StagingError, match="executor cannot apply offline"):
        docker.check_offline_executor(reference, None)
    assert len(commands) == 1
