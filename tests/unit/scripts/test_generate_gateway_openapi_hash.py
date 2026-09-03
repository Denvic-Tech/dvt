import importlib.util
import json
from pathlib import Path
from urllib import error

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts" / "misc" / "generate_gateway_openapi_hash.py"


def load_module():
    spec = importlib.util.spec_from_file_location("generate_gateway_openapi_hash", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload: str) -> None:
        self.payload = payload.encode("utf-8")

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_build_default_openapi_url_handles_public_root() -> None:
    module = load_module()

    assert module.build_default_openapi_url("https://dvt.example") == "https://dvt.example/api/openapi.json"
    assert module.build_default_openapi_url("https://dvt.example/api/") == "https://dvt.example/api/openapi.json"


def test_build_default_openapi_urls_supports_semicolon_separated_public_urls() -> None:
    module = load_module()

    assert module.build_default_openapi_urls("https://dvt.example;http://10.10.10.10") == [
        "https://dvt.example/api/openapi.json",
        "http://10.10.10.10/api/openapi.json",
    ]


def test_canonical_hash_is_stable_for_key_order() -> None:
    module = load_module()

    left = {"paths": {"/a": {"get": {"summary": "x"}}}, "info": {"title": "A"}}
    right = {"info": {"title": "A"}, "paths": {"/a": {"get": {"summary": "x"}}}}

    left_canonical, _ = module.canonicalize_openapi_document(left)
    right_canonical, _ = module.canonicalize_openapi_document(right)

    assert left_canonical == right_canonical
    assert module.calculate_openapi_sha256(left_canonical) == module.calculate_openapi_sha256(right_canonical)


def test_generate_snapshot_fetches_and_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    payload = json.dumps({"openapi": "3.1.0", "paths": {"/ping": {"get": {"operationId": "ping"}}}})

    monkeypatch.setattr(module.request, "urlopen", lambda *_args, **_kwargs: FakeResponse(payload))

    snapshot = module.generate_snapshot("https://dvt.example/api/openapi.json")

    assert snapshot.source_url == "https://dvt.example/api/openapi.json"
    assert snapshot.document["paths"]["/ping"]["get"]["operationId"] == "ping"
    assert snapshot.sha256
    assert snapshot.pretty_json.endswith("\n")


def test_generate_snapshot_from_candidates_falls_back_to_next_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    payload = json.dumps({"openapi": "3.1.0", "paths": {"/ping": {"get": {"operationId": "ping"}}}})

    def fake_urlopen(api_request, timeout):
        if api_request.full_url == "https://unreachable.example/api/openapi.json":
            raise error.URLError("Name or service not known")
        assert api_request.full_url == "http://10.101.9.101/api/openapi.json"
        return FakeResponse(payload)

    monkeypatch.setattr(module.request, "urlopen", fake_urlopen)

    snapshot = module.generate_snapshot_from_candidates(
        [
            "https://unreachable.example/api/openapi.json",
            "http://10.101.9.101/api/openapi.json",
        ]
    )

    assert snapshot.source_url == "http://10.101.9.101/api/openapi.json"
    assert snapshot.document["paths"]["/ping"]["get"]["operationId"] == "ping"


def test_load_openapi_document_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    monkeypatch.setattr(module.request, "urlopen", lambda *_args, **_kwargs: FakeResponse("not-json"))

    with pytest.raises(RuntimeError, match="not valid JSON"):
        module.load_openapi_document("https://dvt.example/api/openapi.json")


def test_resolve_openapi_url_candidates_from_env_supports_multiple_public_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    monkeypatch.delenv("GATEWAY_SDK_OPENAPI_URL", raising=False)
    monkeypatch.setenv("DVT_DEV_PUBLIC_URL", "https://dvt.example;http://10.101.9.101")

    assert module.resolve_openapi_url_candidates_from_env() == [
        "https://dvt.example/api/openapi.json",
        "http://10.101.9.101/api/openapi.json",
    ]
