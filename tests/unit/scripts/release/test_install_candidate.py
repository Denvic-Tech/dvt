"""Regression checks for the exact-candidate install gate and receipt publication."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.release import test_install_candidate as candidate

from services.installation_manager.domain.release_manifest import strict_json

FIXTURES = Path(__file__).resolve().parents[3] / "data/installation_manager/verified_staging"


def inputs(tmp_path):
    from urllib.parse import urlsplit

    manifest = tmp_path / "manifest.json"
    raw = (FIXTURES / "manifest.json").read_bytes()
    manifest.write_bytes(raw)
    release = strict_json(raw)["payload"]
    for role, source in (("compose", "compose.yaml"), ("bootstrap", "bootstrap.sh")):
        descriptor = release["platforms"]["linux/amd64"][role]
        output = tmp_path / urlsplit(descriptor["url"]).path.lstrip("/")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes((FIXTURES / source).read_bytes())
    trust = tmp_path / "trust.json"
    trust.write_text(
        json.dumps(
            {
                "roots": strict_json((FIXTURES / "trust.json").read_bytes())["roots"],
                "revoked_signers": [],
            }
        )
    )
    return manifest, tmp_path, trust


@pytest.mark.parametrize("role", ["compose", "bootstrap"])
def test_packaged_asset_tamper_fails_before_docker(tmp_path, monkeypatch, role):
    manifest, assets, trust = inputs(tmp_path)
    _content, _release, _pin, _files = candidate.verified_inputs(manifest, assets, trust)
    payload = strict_json(manifest.read_bytes())["payload"]
    from urllib.parse import urlsplit

    compose = assets / urlsplit(payload["platforms"]["linux/amd64"][role]["url"]).path.lstrip("/")
    compose.write_bytes(compose.read_bytes() + b"\n")
    calls = []
    monkeypatch.setattr(candidate, "host_docker", lambda *args, **kwargs: calls.append(args))
    args = SimpleNamespace(
        manifest=manifest,
        assets_dir=assets,
        trust=trust,
        output=tmp_path / "receipt.json",
        pipeline_id="42",
        dind_image=candidate.DEFAULT_DIND,
    )
    with pytest.raises(RuntimeError):
        candidate.run_outer(args)
    assert not calls
    assert not args.output.exists()


def test_receipt_binds_exact_envelope_and_distributor_pipeline_contract():
    result = candidate.receipt(b"envelope", "1.24.0-rc4", "12345")
    assert result == {
        "format_version": 1,
        "version": "1.24.0-rc4",
        "manifest_digest": "sha256:4c503ca67761e5c4aaecfe996244c25d8c0b40902d1085c85b4468bd567548c6",
        "result": "passed",
        "run_id": "gitlab-pipeline-12345",
    }


@pytest.mark.parametrize("stage", ["controller", "result", "cleanup"])
def test_failure_never_creates_receipt_and_removes_only_current_test_resources(
    tmp_path, monkeypatch, stage
):
    release = SimpleNamespace(
        version="1.24.0",
        platforms={
            "linux/amd64": SimpleNamespace(
                images={
                    "installation_manager": SimpleNamespace(
                        reference="registry.example.org/manager@sha256:" + "a" * 64,
                    )
                },
            )
        },
    )
    monkeypatch.setattr(candidate, "verified_inputs", lambda *_: (b"exact", release, None, {}))
    monkeypatch.setattr(
        candidate.subprocess, "run", lambda *_args, **_kw: SimpleNamespace(returncode=0)
    )
    calls = []

    def docker(*args, **_kwargs):
        calls.append(args)
        if args[0] == "exec" and stage == "controller":
            raise RuntimeError("failed install")
        if args[0] == "cp" and args[1].endswith(":/case/result.json"):
            Path(args[2]).write_text(
                json.dumps(
                    {
                        **candidate.receipt(b"exact", release.version, "7"),
                        **({"manifest_digest": "sha256:" + "0" * 64} if stage == "result" else {}),
                    }
                )
            )
        if stage == "cleanup" and args[0] == "rm":
            raise RuntimeError("cleanup failed")
        return b""

    monkeypatch.setattr(candidate, "host_docker", docker)
    args = SimpleNamespace(
        manifest=Path("manifest"),
        assets_dir=Path("assets"),
        trust=tmp_path / "trust.json",
        output=tmp_path / "receipt.json",
        pipeline_id="7",
        dind_image=candidate.DEFAULT_DIND,
        registry_config=None,
        timeout=60,
    )
    args.trust.write_text("{}")
    with pytest.raises((RuntimeError, ValueError)):
        candidate.run_outer(args)
    assert not args.output.exists()
    assert any(call[0] == "rm" for call in calls)
    assert all("prune" not in call for call in calls)
    run = next(call for call in calls if call[0] == "run")
    mounts = [run[index + 1] for index, value in enumerate(run) if value == "--mount"]
    assert all("docker.sock" not in mount and "type=bind" not in mount for mount in mounts)
    assert "--publish" not in run and "-p" not in run


@pytest.mark.parametrize("seeded_organization", [True, False])
def test_first_login_setup_follows_the_product_wizard(seeded_organization):
    import httpx

    requests = []

    def handle(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json={"initialized": True})

    status = {
        "initialized": False,
        "steps": [
            {"code": "organization", "completed": seeded_organization},
            {"code": "superadmin", "completed": False},
        ],
    }
    with httpx.Client(base_url="http://fixture", transport=httpx.MockTransport(handle)) as product:
        candidate.finish_setup(product, status, "ci@example.org", "test-password")
    expected = [] if seeded_organization else [("POST", "/api/setup/organization")]
    assert requests == [
        *expected,
        ("POST", "/api/setup/superadmin"),
        ("GET", "/api/setup/status"),
    ]
