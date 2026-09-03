from __future__ import annotations

import sqlalchemy as sa

from services.gateway.deps import dvt_service_files as dvt_service_files_module

from src.modules.file_storage.infra.db_models import DVTServiceFileObjectRecord
from src.modules.pipeline_graph.infra.db_models import (
    GraphNodeRecord,
)
from src.utils.access_control import AccessScope


def _make_load_csv_node(*, project_id: str, user_id: str, organization_id: str, input_values=None) -> GraphNodeRecord:
    return GraphNodeRecord(
        ui_id="node-load-csv",
        type="simpleinputnode",
        position_x=10.0,
        position_y=20.0,
        selected=False,
        name="LoadCSV",
        display_name="Load CSV",
        comment=None,
        input_values=input_values or {},
        project_id=project_id,
        user_id=user_id,
        organization_id=organization_id,
    )


def _make_load_json_node(*, project_id: str, user_id: str, organization_id: str, input_values=None) -> GraphNodeRecord:
    return GraphNodeRecord(
        ui_id="node-load-json",
        type="simpleinputnode",
        position_x=10.0,
        position_y=20.0,
        selected=False,
        name="LoadJSON",
        display_name="Load JSON",
        comment=None,
        input_values=input_values or {},
        project_id=project_id,
        user_id=user_id,
        organization_id=organization_id,
    )


async def test_upload_node_file_input_returns_descriptor_without_graph_mutation(
    gateway_client,
    router_prefix,
    db_session,
    monkeypatch,
    test_user,
    test_user_project,
) -> None:
    monkeypatch.setattr(dvt_service_files_module, "engine", db_session.bind)
    node = _make_load_csv_node(
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
    )
    db_session.add(node)
    db_session.commit()

    response = await gateway_client.post(
        f"{router_prefix}/projects/{test_user_project.id}/graph/nodes/{node.ui_id}/file-inputs/file",
        files={"file": ("data.csv", b"id,name\n1,Alice\n", "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "data.csv"
    assert payload["path"] == "data.csv"
    assert payload["connection"]["type"] == "dvt_service_files"
    assert payload["connection"]["properties"]["project_id"] == test_user_project.id
    assert payload["input_values_patch"] == {
        "connection": {
            "__dvt_type": "const",
            "value": payload["connection"],
        },
        "path": {
            "__dvt_type": "const",
            "value": "data.csv",
        },
    }

    db_session.refresh(node)
    assert node.input_values == {}

    stored_file = db_session.execute(
        sa.select(DVTServiceFileObjectRecord).where(
            DVTServiceFileObjectRecord.project_id == test_user_project.id,
            DVTServiceFileObjectRecord.parent_path == f"node-inputs/{node.ui_id}/file",
            DVTServiceFileObjectRecord.name == "data.csv",
            DVTServiceFileObjectRecord.is_dir == False,  # noqa: E712
        )
    ).scalar_one()
    assert stored_file.content == b"id,name\n1,Alice\n"


async def test_delete_node_file_input_uses_explicit_path_without_graph_mutation(
    gateway_client,
    router_prefix,
    db_session,
    monkeypatch,
    test_user,
    test_user_project,
) -> None:
    monkeypatch.setattr(dvt_service_files_module, "engine", db_session.bind)
    input_values = {
        "connection": {"__dvt_type": "const", "value": {"type": "dvt_service_files"}},
        "path": {"__dvt_type": "const", "value": "data.csv"},
    }
    node = _make_load_csv_node(
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        input_values=input_values,
    )
    db_session.add(node)
    db_session.add(
        DVTServiceFileObjectRecord(
            organization_id=test_user.organization_id,
            project_id=test_user_project.id,
            parent_path=f"node-inputs/{node.ui_id}/file",
            name="data.csv",
            is_dir=False,
            content=b"id,name\n1,Alice\n",
            content_type="text/csv",
            size=16,
            sha256="digest",
        )
    )
    db_session.commit()

    response = await gateway_client.delete(
        f"{router_prefix}/projects/{test_user_project.id}/graph/nodes/{node.ui_id}/file-inputs/file",
        params={"path": "data.csv"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "data.csv"
    assert payload["path"] is None
    assert payload["connection"] is None
    assert payload["input_values_patch"] == {}

    db_session.refresh(node)
    assert node.input_values == input_values

    stored_file = db_session.execute(
        sa.select(DVTServiceFileObjectRecord).where(
            DVTServiceFileObjectRecord.project_id == test_user_project.id,
            DVTServiceFileObjectRecord.parent_path == f"node-inputs/{node.ui_id}/file",
            DVTServiceFileObjectRecord.name == "data.csv",
            DVTServiceFileObjectRecord.is_dir == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    assert stored_file is None


async def test_upload_node_file_input_allows_global_access_scope(
    gateway_client,
    router_prefix,
    db_session,
    monkeypatch,
    test_user,
    test_user_project,
) -> None:
    from services.gateway.routes.project import file_inputs as file_inputs_module

    monkeypatch.setattr(dvt_service_files_module, "engine", db_session.bind)
    monkeypatch.setattr(
        file_inputs_module,
        "get_access_scope",
        lambda _user: AccessScope(organization_id=None, owner_user_id=None),
    )
    node = _make_load_csv_node(
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
    )
    db_session.add(node)
    db_session.commit()

    response = await gateway_client.post(
        f"{router_prefix}/projects/{test_user_project.id}/graph/nodes/{node.ui_id}/file-inputs/file",
        files={"file": ("data.csv", b"id,name\n1,Alice\n", "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == node.ui_id
    assert payload["connection"]["properties"]["project_id"] == test_user_project.id


async def test_upload_node_file_input_supports_load_json(
    gateway_client,
    router_prefix,
    db_session,
    monkeypatch,
    test_user,
    test_user_project,
) -> None:
    monkeypatch.setattr(dvt_service_files_module, "engine", db_session.bind)
    node = _make_load_json_node(
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
    )
    db_session.add(node)
    db_session.commit()

    response = await gateway_client.post(
        f"{router_prefix}/projects/{test_user_project.id}/graph/nodes/{node.ui_id}/file-inputs/file",
        files={"file": ("data.json", b'{"id": 1, "name": "Alice"}', "application/json")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "data.json"
    assert payload["path"] == "data.json"
    assert payload["connection"]["type"] == "dvt_service_files"
    assert payload["input_values_patch"] == {
        "connection": {
            "__dvt_type": "const",
            "value": payload["connection"],
        },
        "path": {
            "__dvt_type": "const",
            "value": "data.json",
        },
    }
