from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.project.infra.db_models import ProjectFolderRecord, ProjectRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskSource
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode


def _create_user(
        session,
        *,
        organization_id: str,
        role: str = DVTDefaultRoles.USER.value,
        email: str | None = None,
) -> UserRecord:
    user = UserRecord(
        email=email or f"user-{uuid4()}@example.com",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=role,
        organization_id=organization_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def set_current_user(gateway_client):
    from usrak.core.dependencies.user import get_optional_user_any

    from services.gateway.main import app
    from services.gateway.routes.organization import crud as organization_crud
    from services.gateway.routes.project import schedule as project_schedule, task as project_task
    from services.gateway.routes.public.organization import crud as public_organization_crud
    from services.gateway.routes.public.project import task as public_project_task

    from src.modules.user.infra.fastapi.dependencies import (
        get_user_access_only,
        get_user_superadmin_access_only,
    )


    def _set(user: UserRecord) -> None:
        dependencies = [
            get_user_superadmin_access_only,
            get_user_access_only,
            get_optional_user_any,
            organization_crud._get_user,
            public_organization_crud._get_user,
            project_schedule._get_user,
            project_task._get_user,
            public_project_task._get_user,
        ]
        for dependency in dependencies:
            app.dependency_overrides[dependency] = lambda user=user: user

    return _set


@pytest.mark.asyncio
async def test_projects_list_and_create(
        gateway_client,
        router_prefix,
        test_user,
        test_user_project,
):
    list_resp = await gateway_client.get(f"{router_prefix}/projects")
    assert list_resp.status_code == 200
    listed_projects = {item["id"]: item for item in list_resp.json()}
    listed_ids = set(listed_projects)
    assert test_user_project.id in listed_ids
    assert listed_projects[test_user_project.id]["user_email"] == test_user.email

    create_resp = await gateway_client.post(
        f"{router_prefix}/projects",
        json={"name": "New Project Async CRUD"},
    )
    assert create_resp.status_code == 200, create_resp.json()
    payload = create_resp.json()
    assert payload["id"]
    assert payload["name"] == "New Project Async CRUD"


@pytest.mark.asyncio
async def test_projects_list_can_sort_by_updated_at_desc_across_root_and_nested_projects(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
):
    folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Flat list folder",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        created_at=datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
    )
    db_session.add(folder)
    db_session.commit()

    newest_nested = ProjectRecord(
        id=str(uuid4()),
        name="Flat newest nested",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        folder_id=folder.id,
        created_at=datetime(2026, 7, 3, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )
    middle_root = ProjectRecord(
        id=str(uuid4()),
        name="Flat middle root",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        created_at=datetime(2026, 7, 2, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
    )
    oldest_root = ProjectRecord(
        id=str(uuid4()),
        name="Flat oldest root",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        created_at=datetime(2026, 7, 1, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
    )
    db_session.add_all([newest_nested, middle_root, oldest_root])
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects",
        params={"sort_by": "updated_at", "sort_order": "desc"},
    )

    assert response.status_code == 200, response.json()
    ordered_ids = [item["id"] for item in response.json()[:3]]
    assert ordered_ids == [newest_nested.id, middle_root.id, oldest_root.id]


@pytest.mark.asyncio
async def test_project_items_lists_root_folders_and_projects(
        gateway_client,
        router_prefix,
        test_user,
        test_user_project,
):
    folder_resp = await gateway_client.post(
        f"{router_prefix}/projects/folders",
        json={"name": "Analytics"},
    )
    assert folder_resp.status_code == 200, folder_resp.json()
    assert folder_resp.json()["user_email"] == test_user.email

    response = await gateway_client.get(
        f"{router_prefix}/projects/items",
        params={"limit": 10, "offset": 0},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["total"] >= 2
    assert payload["limit"] == 10
    assert payload["offset"] == 0
    assert payload["folder_id"] is None

    folder_items = [item for item in payload["items"] if item["type"] == "folder"]
    project_items = [item for item in payload["items"] if item["type"] == "project"]
    assert any(item["folder"]["id"] == folder_resp.json()["id"] for item in folder_items)
    assert any(item["folder"]["user_email"] == test_user.email for item in folder_items)
    assert any(item["project"]["id"] == test_user_project.id for item in project_items)


@pytest.mark.asyncio
async def test_project_can_be_created_inside_folder_and_listed_by_folder(
        gateway_client,
        router_prefix,
):
    folder_resp = await gateway_client.post(
        f"{router_prefix}/projects/folders",
        json={"name": "Folder for project"},
    )
    assert folder_resp.status_code == 200, folder_resp.json()
    folder_id = folder_resp.json()["id"]

    create_resp = await gateway_client.post(
        f"{router_prefix}/projects",
        json={"name": "Nested Project", "folder_id": folder_id},
    )
    assert create_resp.status_code == 200, create_resp.json()
    assert create_resp.json()["folder_id"] == folder_id

    root_resp = await gateway_client.get(f"{router_prefix}/projects/items")
    assert root_resp.status_code == 200, root_resp.json()
    root_project_ids = [
        item["project"]["id"]
        for item in root_resp.json()["items"]
        if item["type"] == "project"
    ]
    assert create_resp.json()["id"] not in root_project_ids

    folder_items_resp = await gateway_client.get(
        f"{router_prefix}/projects/items",
        params={"folder_id": folder_id},
    )
    assert folder_items_resp.status_code == 200, folder_items_resp.json()
    folder_project_ids = [
        item["project"]["id"]
        for item in folder_items_resp.json()["items"]
        if item["type"] == "project"
    ]
    assert create_resp.json()["id"] in folder_project_ids


@pytest.mark.asyncio
async def test_project_items_pagination_returns_total_and_has_more(
        gateway_client,
        router_prefix,
):
    for name in ["Alpha", "Beta", "Gamma"]:
        response = await gateway_client.post(
            f"{router_prefix}/projects/folders",
            json={"name": name},
        )
        assert response.status_code == 200, response.json()

    page = await gateway_client.get(
        f"{router_prefix}/projects/items",
        params={"limit": 2, "offset": 0},
    )

    assert page.status_code == 200, page.json()
    payload = page.json()
    assert payload["total"] >= 3
    assert len(payload["items"]) == 2
    assert payload["has_more"] is True
    assert [item["type"] for item in payload["items"]] == ["folder", "folder"]


@pytest.mark.asyncio
async def test_project_items_organization_filter_preserves_user_owner_scope(
        gateway_client,
        router_prefix,
        test_user,
        test_user_project,
        test_admin_project,
):
    response = await gateway_client.get(
        f"{router_prefix}/projects/items",
        params={"organization_id": test_user.organization_id, "limit": 20},
    )

    assert response.status_code == 200, response.json()
    project_ids = [
        item["project"]["id"]
        for item in response.json()["items"]
        if item["type"] == "project"
    ]
    assert test_user_project.id in project_ids
    assert test_admin_project.id not in project_ids


@pytest.mark.asyncio
async def test_project_items_can_sort_by_updated_at_desc_for_projects_and_folders(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
):
    parent_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Updated Sort Parent",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        created_at=datetime(2026, 5, 2, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 2, 8, 0, tzinfo=UTC),
    )
    db_session.add(parent_folder)
    db_session.commit()

    older_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Updated Sort Folder Old",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        parent_id=parent_folder.id,
        created_at=datetime(2026, 5, 3, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
    )
    newer_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Updated Sort Folder New",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        parent_id=parent_folder.id,
        created_at=datetime(2026, 5, 3, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 3, 11, 0, tzinfo=UTC),
    )
    older_project = ProjectRecord(
        id=str(uuid4()),
        name="Updated Sort Project Old",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        folder_id=parent_folder.id,
        created_at=datetime(2026, 5, 3, 7, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 3, 9, 0, tzinfo=UTC),
    )
    newer_project = ProjectRecord(
        id=str(uuid4()),
        name="Updated Sort Project New",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        folder_id=parent_folder.id,
        created_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
    )
    db_session.add_all([older_folder, newer_folder, older_project, newer_project])
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/items",
        params={
            "limit": 20,
            "folder_id": parent_folder.id,
            "sort_by": "updated_at",
            "sort_order": "desc",
        },
    )

    assert response.status_code == 200, response.json()
    ordered_items = [
        (
            item["type"],
            item["folder"]["id"] if item["type"] == "folder" else item["project"]["id"],
        )
        for item in response.json()["items"]
    ]
    assert ordered_items == [
        ("project", newer_project.id),
        ("folder", newer_folder.id),
        ("folder", older_folder.id),
        ("project", older_project.id),
    ]


@pytest.mark.asyncio
async def test_superadmin_can_get_project_items_for_requested_organization(
        gateway_client,
        router_prefix,
        db_session,
        set_current_user,
        test_superadmin_user,
):
    set_current_user(test_superadmin_user)
    own_project = ProjectRecord(
        id=str(uuid4()),
        name="Superadmin own org project",
        user_id=test_superadmin_user.id,
        organization_id=test_superadmin_user.organization_id,
    )
    other_organization = OrganizationRecord(name=f"Items org {uuid4()}")
    db_session.add_all([own_project, other_organization])
    db_session.commit()
    db_session.refresh(other_organization)
    other_user = _create_user(
        db_session,
        organization_id=other_organization.id,
    )
    other_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Other org folder",
        user_id=other_user.id,
        organization_id=other_organization.id,
    )
    other_project = ProjectRecord(
        id=str(uuid4()),
        name="Other org project",
        user_id=other_user.id,
        organization_id=other_organization.id,
    )
    db_session.add_all([other_folder, other_project])
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/items",
        params={"organization_id": other_organization.id, "limit": 20},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    project_ids = {
        item["project"]["id"]
        for item in payload["items"]
        if item["type"] == "project"
    }
    folder_ids = {
        item["folder"]["id"]
        for item in payload["items"]
        if item["type"] == "folder"
    }
    assert other_project.id in project_ids
    assert own_project.id not in project_ids
    assert other_folder.id in folder_ids


@pytest.mark.asyncio
async def test_admin_cannot_get_project_items_for_other_organization(
        gateway_client,
        router_prefix,
        db_session,
        set_current_user,
        test_admin_user,
):
    set_current_user(test_admin_user)
    other_organization = OrganizationRecord(name=f"Forbidden org {uuid4()}")
    db_session.add(other_organization)
    db_session.commit()
    db_session.refresh(other_organization)

    response = await gateway_client.get(
        f"{router_prefix}/projects/items",
        params={"organization_id": other_organization.id, "limit": 20},
    )

    assert response.status_code == 403, response.json()
    assert other_organization.id in response.text


@pytest.mark.asyncio
async def test_project_folder_depth_is_limited(
        gateway_client,
        router_prefix,
):
    parent_id = None
    for level in range(5):
        response = await gateway_client.post(
            f"{router_prefix}/projects/folders",
            json={"name": f"Level {level}", "parent_id": parent_id},
        )
        assert response.status_code == 200, response.json()
        parent_id = response.json()["id"]

    too_deep = await gateway_client.post(
        f"{router_prefix}/projects/folders",
        json={"name": "Too deep", "parent_id": parent_id},
    )

    assert too_deep.status_code == 400, too_deep.json()


@pytest.mark.asyncio
async def test_project_folder_delete_rejects_non_empty_folder(
        gateway_client,
        router_prefix,
):
    folder_resp = await gateway_client.post(
        f"{router_prefix}/projects/folders",
        json={"name": "Non empty"},
    )
    assert folder_resp.status_code == 200, folder_resp.json()
    folder_id = folder_resp.json()["id"]

    create_resp = await gateway_client.post(
        f"{router_prefix}/projects",
        json={"name": "Project in folder", "folder_id": folder_id},
    )
    assert create_resp.status_code == 200, create_resp.json()

    delete_resp = await gateway_client.delete(f"{router_prefix}/projects/folders/{folder_id}")

    assert delete_resp.status_code == 409, delete_resp.json()


@pytest.mark.asyncio
async def test_search_projects_and_folders_by_name_contains_and_respects_access_scope(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
        test_admin_project,
):
    matching_project = ProjectRecord(
        id=str(uuid4()),
        name="Monthly Finance Report",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
    )
    other_matching_project = ProjectRecord(
        id=str(uuid4()),
        name="finance cleanup",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
    )
    inaccessible_matching_project = ProjectRecord(
        id=str(uuid4()),
        name="Finance Admin Only",
        user_id=test_admin_project.user_id,
        organization_id=test_admin_project.organization_id,
    )
    matching_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Finance Folder",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
    )
    inaccessible_matching_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Finance Admin Folder",
        user_id=test_admin_project.user_id,
        organization_id=test_admin_project.organization_id,
    )
    db_session.add_all([
        matching_project,
        other_matching_project,
        inaccessible_matching_project,
        matching_folder,
        inaccessible_matching_folder,
    ])
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/search",
        params={"name": "FINANCE", "limit": 10},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    found_project_ids = {
        item["project"]["id"]
        for item in payload["items"]
        if item["type"] == "project"
    }
    found_folder_ids = {
        item["folder"]["id"]
        for item in payload["items"]
        if item["type"] == "folder"
    }
    assert matching_project.id in found_project_ids
    assert other_matching_project.id in found_project_ids
    assert inaccessible_matching_project.id not in found_project_ids
    assert matching_folder.id in found_folder_ids
    assert inaccessible_matching_folder.id not in found_folder_ids
    assert payload["total"] == 3
    assert payload["has_more"] is False


@pytest.mark.asyncio
async def test_search_projects_organization_filter_preserves_user_owner_scope(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
        test_user_project,
        test_admin_project,
):
    matching_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Scoped Finance Folder",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
    )
    inaccessible_matching_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Scoped Finance Admin Folder",
        user_id=test_admin_project.user_id,
        organization_id=test_admin_project.organization_id,
    )
    db_session.add_all([matching_folder, inaccessible_matching_folder])
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/search",
        params={
            "name": "project",
            "organization_id": test_user.organization_id,
            "limit": 20,
        },
    )

    assert response.status_code == 200, response.json()
    project_ids = {
        item["project"]["id"]
        for item in response.json()["items"]
        if item["type"] == "project"
    }
    assert test_user_project.id in project_ids
    assert test_admin_project.id not in project_ids


@pytest.mark.asyncio
async def test_superadmin_can_search_projects_for_requested_organization(
        gateway_client,
        router_prefix,
        db_session,
        set_current_user,
        test_superadmin_user,
):
    set_current_user(test_superadmin_user)
    own_project = ProjectRecord(
        id=str(uuid4()),
        name="Finance Own Org Project",
        user_id=test_superadmin_user.id,
        organization_id=test_superadmin_user.organization_id,
    )
    other_organization = OrganizationRecord(name=f"Search org {uuid4()}")
    db_session.add_all([own_project, other_organization])
    db_session.commit()
    db_session.refresh(other_organization)
    other_user = _create_user(
        db_session,
        organization_id=other_organization.id,
    )
    other_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Finance Other Org Folder",
        user_id=other_user.id,
        organization_id=other_organization.id,
    )
    other_project = ProjectRecord(
        id=str(uuid4()),
        name="Finance Other Org Project",
        user_id=other_user.id,
        organization_id=other_organization.id,
    )
    db_session.add_all([other_folder, other_project])
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/search",
        params={
            "name": "finance",
            "organization_id": other_organization.id,
            "limit": 20,
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    project_ids = {
        item["project"]["id"]
        for item in payload["items"]
        if item["type"] == "project"
    }
    folder_ids = {
        item["folder"]["id"]
        for item in payload["items"]
        if item["type"] == "folder"
    }
    assert other_project.id in project_ids
    assert own_project.id not in project_ids
    assert other_folder.id in folder_ids


@pytest.mark.asyncio
async def test_admin_cannot_search_projects_for_other_organization(
        gateway_client,
        router_prefix,
        db_session,
        set_current_user,
        test_admin_user,
):
    set_current_user(test_admin_user)
    other_organization = OrganizationRecord(name=f"Search forbidden org {uuid4()}")
    db_session.add(other_organization)
    db_session.commit()
    db_session.refresh(other_organization)

    response = await gateway_client.get(
        f"{router_prefix}/projects/search",
        params={
            "name": "finance",
            "organization_id": other_organization.id,
            "limit": 20,
        },
    )

    assert response.status_code == 403, response.json()
    assert other_organization.id in response.text


@pytest.mark.asyncio
async def test_search_can_filter_by_folder_and_item_type(
        gateway_client,
        router_prefix,
):
    folder_resp = await gateway_client.post(
        f"{router_prefix}/projects/folders",
        json={"name": "Search folder"},
    )
    assert folder_resp.status_code == 200, folder_resp.json()
    folder_id = folder_resp.json()["id"]

    in_folder_resp = await gateway_client.post(
        f"{router_prefix}/projects",
        json={"name": "Sales Search Target", "folder_id": folder_id},
    )
    assert in_folder_resp.status_code == 200, in_folder_resp.json()

    root_resp = await gateway_client.post(
        f"{router_prefix}/projects",
        json={"name": "Sales Search Target Root"},
    )
    assert root_resp.status_code == 200, root_resp.json()

    response = await gateway_client.get(
        f"{router_prefix}/projects/search",
        params={
            "name": "search target",
            "folder_id": folder_id,
            "item_type": "project",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["total"] == 1
    assert payload["has_more"] is False
    assert [item["project"]["id"] for item in payload["items"]] == [in_folder_resp.json()["id"]]

    folder_only = await gateway_client.get(
        f"{router_prefix}/projects/search",
        params={"name": "Search folder", "item_type": "folder"},
    )

    assert folder_only.status_code == 200, folder_only.json()
    assert folder_only.json()["total"] == 1
    assert folder_only.json()["items"][0]["type"] == "folder"
    assert folder_only.json()["items"][0]["folder"]["id"] == folder_id


@pytest.mark.asyncio
async def test_search_can_sort_by_updated_at_asc(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
):
    older_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Finance Sort Folder Old",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        created_at=datetime(2026, 5, 6, 6, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 6, 8, 0, tzinfo=UTC),
    )
    newer_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Finance Sort Folder New",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        created_at=datetime(2026, 5, 6, 7, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 6, 11, 0, tzinfo=UTC),
    )
    older_project = ProjectRecord(
        id=str(uuid4()),
        name="Finance Sort Project Old",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        created_at=datetime(2026, 5, 6, 5, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 6, 9, 0, tzinfo=UTC),
    )
    newer_project = ProjectRecord(
        id=str(uuid4()),
        name="Finance Sort Project New",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        created_at=datetime(2026, 5, 6, 8, 30, tzinfo=UTC),
        updated_at=datetime(2026, 5, 6, 12, 0, tzinfo=UTC),
    )
    db_session.add_all([older_folder, newer_folder, older_project, newer_project])
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/search",
        params={
            "name": "finance sort",
            "limit": 20,
            "sort_by": "updated_at",
            "sort_order": "asc",
        },
    )

    assert response.status_code == 200, response.json()
    ordered_items = [
        (
            item["type"],
            item["folder"]["id"] if item["type"] == "folder" else item["project"]["id"],
        )
        for item in response.json()["items"]
    ]
    assert ordered_items == [
        ("folder", older_folder.id),
        ("project", older_project.id),
        ("folder", newer_folder.id),
        ("project", newer_project.id),
    ]


@pytest.mark.asyncio
async def test_project_items_include_five_last_runs_from_any_source(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
        test_user_project,
):
    base_time = datetime(2026, 5, 8, 10, 0, tzinfo=UTC)
    scheduler_runs = [
        TaskRecord(
            task_id=f"scheduler-run-{index}",
            mode=PipelineExecutionMode.FULL,
            status=TaskExecutionStatus.SUCCESS if index % 2 == 0 else TaskExecutionStatus.ERROR,
            source=TaskSource.SCHEDULER,
            queued_at=base_time + timedelta(minutes=index),
            started_at=base_time + timedelta(minutes=index, seconds=10),
            finished_at=base_time + timedelta(minutes=index, seconds=20),
            message=f"run {index}",
            termination_reason="NODE_FAILURE" if index % 2 else None,
            user_id=test_user.id,
            organization_id=test_user.organization_id,
            project_id=test_user_project.id,
        )
        for index in range(6)
    ]
    ui_run = TaskRecord(
        task_id="ui-run-included",
        mode=PipelineExecutionMode.FULL,
        status=TaskExecutionStatus.SUCCESS,
        source=TaskSource.UI,
        queued_at=base_time + timedelta(hours=1),
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        project_id=test_user_project.id,
    )
    metadata_run = TaskRecord(
        task_id="metadata-run-ignored",
        mode=PipelineExecutionMode.METADATA_ONLY,
        status=TaskExecutionStatus.SUCCESS,
        source=TaskSource.UI,
        queued_at=base_time + timedelta(hours=2),
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        project_id=test_user_project.id,
    )
    db_session.add_all([*scheduler_runs, ui_run, metadata_run])
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/items",
        params={"limit": 20},
    )

    assert response.status_code == 200, response.json()
    project_item = next(
        item
        for item in response.json()["items"]
        if item["type"] == "project" and item["project"]["id"] == test_user_project.id
    )
    last_run_ids = [run["task_id"] for run in project_item["project"]["last_runs"]]
    assert last_run_ids == [
        "ui-run-included",
        "scheduler-run-5",
        "scheduler-run-4",
        "scheduler-run-3",
        "scheduler-run-2",
    ]
    assert "metadata-run-ignored" not in last_run_ids


@pytest.mark.asyncio
async def test_update_and_delete_project(
        gateway_client,
        router_prefix,
        test_user_project,
):
    patch_resp = await gateway_client.patch(
        f"{router_prefix}/projects/{test_user_project.id}",
        json={"name": "Renamed Project"},
    )
    assert patch_resp.status_code == 200, patch_resp.json()
    assert patch_resp.json()["name"] == "Renamed Project"

    delete_resp = await gateway_client.delete(
        f"{router_prefix}/projects/{test_user_project.id}"
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["success"] is True


@pytest.mark.asyncio
async def test_admin_can_move_project_into_other_users_folder_in_same_organization(
        gateway_client,
        router_prefix,
        db_session,
        set_current_user,
        test_admin_user,
        test_user_project,
):
    set_current_user(test_admin_user)
    target_user = _create_user(
        db_session,
        organization_id=test_admin_user.organization_id,
    )
    target_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Admin target folder",
        user_id=target_user.id,
        organization_id=test_admin_user.organization_id,
    )
    db_session.add(target_folder)
    db_session.commit()

    response = await gateway_client.patch(
        f"{router_prefix}/projects/{test_user_project.id}",
        json={"folder_id": target_folder.id},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["folder_id"] == target_folder.id
    db_session.refresh(test_user_project)
    assert test_user_project.folder_id == target_folder.id


@pytest.mark.asyncio
async def test_admin_can_move_folder_into_other_users_folder_in_same_organization(
        gateway_client,
        router_prefix,
        db_session,
        set_current_user,
        test_admin_user,
        test_user,
):
    set_current_user(test_admin_user)
    source_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Source folder",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
    )
    target_user = _create_user(
        db_session,
        organization_id=test_admin_user.organization_id,
    )
    target_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Target folder",
        user_id=target_user.id,
        organization_id=test_admin_user.organization_id,
    )
    db_session.add_all([source_folder, target_folder])
    db_session.commit()

    response = await gateway_client.patch(
        f"{router_prefix}/projects/folders/{source_folder.id}",
        json={"parent_id": target_folder.id},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["parent_id"] == target_folder.id
    db_session.refresh(source_folder)
    assert source_folder.parent_id == target_folder.id


@pytest.mark.asyncio
async def test_admin_cannot_move_project_into_other_organization_folder(
        gateway_client,
        router_prefix,
        db_session,
        set_current_user,
        test_admin_user,
        test_user_project,
):
    set_current_user(test_admin_user)
    other_organization = OrganizationRecord(name=f"Other org {uuid4()}")
    db_session.add(other_organization)
    db_session.commit()
    db_session.refresh(other_organization)
    other_user = _create_user(
        db_session,
        organization_id=other_organization.id,
    )
    other_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Cross org folder",
        user_id=other_user.id,
        organization_id=other_organization.id,
    )
    db_session.add(other_folder)
    db_session.commit()

    response = await gateway_client.patch(
        f"{router_prefix}/projects/{test_user_project.id}",
        json={"folder_id": other_folder.id},
    )

    assert response.status_code == 404, response.json()
    db_session.refresh(test_user_project)
    assert test_user_project.folder_id is None


@pytest.mark.asyncio
async def test_superadmin_can_move_project_into_other_organization_folder(
        gateway_client,
        router_prefix,
        db_session,
        set_current_user,
        test_superadmin_user,
        test_user_project,
):
    set_current_user(test_superadmin_user)
    other_organization = OrganizationRecord(name=f"Other org {uuid4()}")
    db_session.add(other_organization)
    db_session.commit()
    db_session.refresh(other_organization)
    other_user = _create_user(
        db_session,
        organization_id=other_organization.id,
    )
    other_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Superadmin target folder",
        user_id=other_user.id,
        organization_id=other_organization.id,
    )
    db_session.add(other_folder)
    db_session.commit()

    response = await gateway_client.patch(
        f"{router_prefix}/projects/{test_user_project.id}",
        json={"folder_id": other_folder.id},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["folder_id"] == other_folder.id
    db_session.refresh(test_user_project)
    assert test_user_project.folder_id == other_folder.id


@pytest.mark.asyncio
async def test_user_cannot_move_project_into_other_users_folder(
        gateway_client,
        router_prefix,
        db_session,
        test_user,
        test_user_project,
):
    other_user = _create_user(
        db_session,
        organization_id=test_user.organization_id,
    )
    other_folder = ProjectFolderRecord(
        id=str(uuid4()),
        name="Other user's folder",
        user_id=other_user.id,
        organization_id=test_user.organization_id,
    )
    db_session.add(other_folder)
    db_session.commit()

    response = await gateway_client.patch(
        f"{router_prefix}/projects/{test_user_project.id}",
        json={"folder_id": other_folder.id},
    )

    assert response.status_code == 404, response.json()
    db_session.refresh(test_user_project)
    assert test_user_project.folder_id is None


@pytest.mark.asyncio
async def test_batch_delete_projects_deletes_found_and_ignores_missing(
        gateway_client,
        router_prefix,
        db_session,
        test_user_project,
        test_admin_project,
):
    missing_project_id = str(uuid4())

    response = await gateway_client.request(
        "DELETE",
        f"{router_prefix}/projects/batch",
        json={
            "project_ids": [
                test_user_project.id,
                test_admin_project.id,
                missing_project_id,
            ]
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["success"] is True
    assert "Projects deleted: 1" in payload["message"]

    deleted_project = db_session.get(ProjectRecord, test_user_project.id)
    inaccessible_project = db_session.get(ProjectRecord, test_admin_project.id)
    assert deleted_project.is_deleted is True
    assert inaccessible_project.is_deleted is False


@pytest.mark.asyncio
async def test_batch_delete_projects_returns_404_when_nothing_accessible(
        gateway_client,
        router_prefix,
        test_admin_project,
):
    missing_project_id = str(uuid4())

    response = await gateway_client.request(
        "DELETE",
        f"{router_prefix}/projects/batch",
        json={
            "project_ids": [
                test_admin_project.id,
                missing_project_id,
            ]
        },
    )

    assert response.status_code == 404, response.json()
    assert test_admin_project.id in response.text
    assert missing_project_id in response.text
