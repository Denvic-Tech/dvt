import pytest
import requests

from src.node_dsl.node_typing import IO
from src.node_dsl.registry import definitions as definitions_registry
from src.nodes.extract.http_request import HTTPRequest


def _node(**kwargs) -> HTTPRequest:
    return HTTPRequest(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        url="https://example.com",
        **kwargs,
    )


def _expr(value: str) -> dict[str, str]:
    return {
        "__dvt_type": "expr",
        "value": value,
        "expression_kind": "single",
    }


def _collect_local_refs(value) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            refs.add(ref)
        for nested in value.values():
            refs.update(_collect_local_refs(nested))
    elif isinstance(value, list):
        for nested in value:
            refs.update(_collect_local_refs(nested))
    return refs


def _resolve_local_ref(schema: dict, ref: str):
    current = schema
    for part in ref.removeprefix("#/").split("/"):
        assert isinstance(current, dict)
        assert part in current, f"JSON Schema ref {ref!r} cannot be resolved at {part!r}"
        current = current[part]
    return current


def test_node_definition_exposes_single_nested_auth_input():
    definition = definitions_registry._create_node_base_definition(HTTPRequest)

    assert "auth" in definition.input_definitions
    assert "auth_type" not in definition.input_definitions
    assert "auth_username" not in definition.input_definitions
    assert "auth_password" not in definition.input_definitions
    assert "auth_token" not in definition.input_definitions
    assert "cert_file_path" not in definition.input_definitions
    assert "key_file_path" not in definition.input_definitions
    assert "key_password" not in definition.input_definitions

    auth_input = definition.input_definitions["auth"]
    assert auth_input.type == IO.SCHEMA
    assert auth_input.default == {"type": "none"}
    assert auth_input.schema is not None
    assert "anyOf" in auth_input.schema or "oneOf" in auth_input.schema

    local_refs = _collect_local_refs(auth_input.schema)
    assert local_refs
    for ref in local_refs:
        _resolve_local_ref(auth_input.schema, ref)


def test_node_definition_exposes_json_payload_as_object_or_array_schema():
    definition = definitions_registry._create_node_base_definition(HTTPRequest)

    payload_input = definition.input_definitions["json_payload"]
    assert payload_input.type == IO.SCHEMA
    assert payload_input.default is None
    assert payload_input.optional is True
    assert payload_input.schema is not None

    variants = payload_input.schema.get("anyOf") or payload_input.schema.get("oneOf") or []
    variant_types = {variant.get("type") for variant in variants if isinstance(variant, dict)}
    assert {"object", "array"}.issubset(variant_types)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"key": "value"},
        ["some_String"],
        [{"key": "value"}],
        [],
        {},
    ],
)
async def test_validate_accepts_json_payload_objects_and_arrays(payload):
    node = _node(method="POST", json_payload=payload)

    await node.validate()


@pytest.mark.asyncio
async def test_validate_rejects_scalar_json_payload():
    node = _node(method="POST")
    node.json_payload = "scalar"

    with pytest.raises(Exception, match="json_payload.*объектом, массивом"):
        await node.validate()


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name", ["headers", "params", "data"])
async def test_validate_keeps_mapping_only_fields_object_only(field_name):
    node = _node(method="POST")
    setattr(node, field_name, ["not", "an", "object"])

    with pytest.raises(Exception, match=field_name):
        await node.validate()


def test_prepare_args_preserves_json_array_payload():
    request_kwargs = _node(
        method="POST",
        json_payload=["some_String", {"nested": [1, 2]}],
    )._prepare_args()

    assert request_kwargs["json"] == ["some_String", {"nested": [1, 2]}]
    assert "data" not in request_kwargs


def test_prepare_args_sends_empty_json_array_and_object():
    assert _node(method="POST", json_payload=[])._prepare_args()["json"] == []
    assert _node(method="POST", json_payload={})._prepare_args()["json"] == {}


def test_prepare_args_keeps_legacy_form_data_fallback_for_empty_json_object():
    request_kwargs = _node(
        method="POST",
        json_payload={},
        data={"field": "value"},
    )._prepare_args()

    assert request_kwargs["data"] == {"field": "value"}
    assert "json" not in request_kwargs


def test_prepare_args_normalizes_json_compatible_tuple_payload_to_array():
    node = _node(method="POST")
    node.json_payload = ("one", {"two": (2, 3)})

    request_kwargs = node._prepare_args()

    assert request_kwargs["json"] == ["one", {"two": [2, 3]}]


def test_prepare_args_keeps_auth_disabled_by_default():
    request_kwargs = _node(headers={"Authorization": "Custom value"})._prepare_args()

    assert "auth" not in request_kwargs
    assert "cert" not in request_kwargs
    assert request_kwargs["headers"] == {"Authorization": "Custom value"}


def test_prepare_args_accepts_explicit_none_auth():
    request_kwargs = _node(
        auth={"type": "none"},
        headers={"Authorization": "Custom value"},
    )._prepare_args()

    assert "auth" not in request_kwargs
    assert "cert" not in request_kwargs
    assert request_kwargs["headers"] == {"Authorization": "Custom value"}


def test_prepare_args_adds_basic_auth():
    request_kwargs = _node(
        auth={
            "type": "basic",
            "username": "alice",
            "password": "secret",
        },
    )._prepare_args()

    auth = request_kwargs["auth"]
    assert isinstance(auth, requests.auth.HTTPBasicAuth)
    assert auth.username == "alice"
    assert auth.password == "secret"


@pytest.mark.asyncio
async def test_validate_accepts_basic_auth_fields_as_variable_expressions():
    node = _node(
        input_variables={
            "login": {"name": "login", "value": "alice"},
            "pwd": {"name": "pwd", "value": "secret"},
        },
        auth={
            "type": "basic",
            "username": _expr("login"),
            "password": _expr("pwd"),
        },
    )

    await node.validate()


def test_prepare_args_resolves_basic_auth_variable_expressions():
    request_kwargs = _node(
        input_variables={
            "login": {"name": "login", "value": "alice"},
            "pwd": {"name": "pwd", "value": "secret"},
        },
        auth={
            "type": "basic",
            "username": _expr("login"),
            "password": _expr("pwd"),
        },
    )._prepare_args()

    auth = request_kwargs["auth"]
    assert isinstance(auth, requests.auth.HTTPBasicAuth)
    assert auth.username == "alice"
    assert auth.password == "secret"


def test_prepare_args_adds_digest_auth():
    request_kwargs = _node(
        auth={
            "type": "digest",
            "username": "alice",
            "password": "secret",
        },
    )._prepare_args()

    auth = request_kwargs["auth"]
    assert isinstance(auth, requests.auth.HTTPDigestAuth)
    assert auth.username == "alice"
    assert auth.password == "secret"


def test_prepare_args_oauth2_overrides_manual_authorization_header():
    request_kwargs = _node(
        headers={
            "Authorization": "Basic old",
            "authorization": "Bearer old",
            "Accept": "application/json",
        },
        auth={
            "type": "oauth2",
            "token": "token-value",
        },
    )._prepare_args()

    assert request_kwargs["headers"] == {
        "Authorization": "Bearer token-value",
        "Accept": "application/json",
    }


def test_prepare_args_resolves_oauth2_token_variable_expression():
    request_kwargs = _node(
        input_variables={
            "token": {"name": "token", "value": "token-value"},
        },
        auth={
            "type": "oauth2",
            "token": _expr("token"),
        },
    )._prepare_args()

    assert request_kwargs["headers"] == {
        "Authorization": "Bearer token-value",
    }


def test_prepare_args_basic_removes_manual_authorization_header():
    request_kwargs = _node(
        headers={
            "Authorization": "Basic old",
            "Accept": "application/json",
        },
        auth={
            "type": "basic",
            "username": "alice",
            "password": "secret",
        },
    )._prepare_args()

    assert request_kwargs["headers"] == {"Accept": "application/json"}


def test_prepare_args_adds_single_file_client_certificate():
    request_kwargs = _node(
        auth={
            "type": "file_cert",
            "cert_file_path": "/tmp/client.pem",
        },
    )._prepare_args()

    assert request_kwargs["cert"] == "/tmp/client.pem"


def test_prepare_args_adds_cert_key_pair():
    request_kwargs = _node(
        auth={
            "type": "file_cert",
            "cert_file_path": "/tmp/client.crt",
            "key_file_path": "/tmp/client.key",
        },
    )._prepare_args()

    assert request_kwargs["cert"] == ("/tmp/client.crt", "/tmp/client.key")


@pytest.mark.parametrize(
    ("auth", "message"),
    [
        (
                {"type": "basic", "username": "alice"},
                "password",
        ),
        (
                {"type": "digest", "password": "secret"},
                "username",
        ),
        (
                {"type": "oauth2"},
                "token",
        ),
        (
                {"type": "file_cert"},
                "cert_file_path",
        ),
        (
                {
                    "type": "file_cert",
                    "cert_file_path": "/tmp/client.crt",
                    "key_password": "secret",
                },
                "requests не поддерживает пароль приватного ключа",
        ),
    ],
)
def test_prepare_args_validates_auth_settings(auth, message):
    with pytest.raises(ValueError, match=message):
        _node(auth=auth)._prepare_args()


def test_prepare_args_validates_unknown_auth_type():
    with pytest.raises(ValueError, match="auth"):
        _node(auth={"type": "unknown"})._prepare_args()
