from datetime import UTC, datetime

import pytest

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.data_catalog.domain import (
    CatalogViewer,
    Dataset,
    DatasetField,
    DatasetLink,
    DatasetSearchQuery,
    FieldStatus,
    LinkDirection,
    PhysicalLocator,
    ResolvedVia,
    ViewerScope,
)
from src.modules.data_catalog.infra import (
    SQLAlchemyDatasetConnectionRepository,
    SQLAlchemyDatasetFieldRepository,
    SQLAlchemyDatasetLinkRepository,
    SQLAlchemyDatasetRepository,
)
from src.modules.db_connection.infra.db_models import DVTStoredConnectionRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord

NOW = datetime(2026, 10, 7, tzinfo=UTC)


async def _seed(session):
    organization = OrganizationRecord(name="Org")
    session.add(organization)
    await session.flush()
    users = {}
    for key in ("owner", "other"):
        user = UserRecord(
            email=f"{key}@example.com",
            hashed_password="h",
            auth_provider="email",
            is_verified=True,
            is_active=True,
            role=DVTDefaultRoles.USER.value,
            organization_id=organization.id,
        )
        session.add(user)
        await session.flush()
        users[key] = user
    project = ProjectRecord(id="p1", name="P", user_id=users["owner"].id, organization_id=organization.id)
    deleted = ProjectRecord(
        id="p-deleted", name="Gone", user_id=users["owner"].id, organization_id=organization.id, is_deleted=True
    )
    session.add_all([project, deleted])
    session.add(
        DVTStoredConnectionRecord(
            id="conn-owner",
            name="pg",
            kind="sql",
            type="postgres",
            properties_json={"host": "db", "port": 5432, "database": "main"},
            user_id=users["owner"].id,
            organization_id=organization.id,
        )
    )
    await session.flush()
    return organization, users


def _dataset(org_id: str, table: str) -> Dataset:
    return Dataset(
        id=f"ds-{table}",
        organization_id=org_id,
        locator=PhysicalLocator("postgresql", "db", 5432, "main", "public", table),
        physical_key=f"postgresql://db:5432/main/public/{table}",
        created_at=NOW,
        updated_at=NOW,
    )


def _link(dataset_id: str, project_id: str, org_id: str, node_id: str, direction=LinkDirection.READ) -> DatasetLink:
    return DatasetLink(
        id=f"{project_id}-{node_id}",
        dataset_id=dataset_id,
        project_id=project_id,
        organization_id=org_id,
        node_id=node_id,
        node_name="ReadTableFromDBV3",
        direction=direction,
        resolved_via=ResolvedVia.CONST,
        graph_revision=1,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_upsert_returns_existing_dataset_for_same_physical_key(async_test_db_session):
    organization, _ = await _seed(async_test_db_session)
    repo = SQLAlchemyDatasetRepository(async_test_db_session)

    first = await repo.upsert(_dataset(organization.id, "t"))
    duplicate = _dataset(organization.id, "t")
    duplicate.id = "another-id"
    second = await repo.upsert(duplicate)

    assert second.id == first.id == "ds-t"


@pytest.mark.asyncio
async def test_visibility_through_projects_connections_and_admin_scope(async_test_db_session):
    organization, users = await _seed(async_test_db_session)
    datasets = SQLAlchemyDatasetRepository(async_test_db_session)
    links = SQLAlchemyDatasetLinkRepository(async_test_db_session)
    connections = SQLAlchemyDatasetConnectionRepository(async_test_db_session)

    via_project = await datasets.upsert(_dataset(organization.id, "via_project"))
    via_connection = await datasets.upsert(_dataset(organization.id, "via_connection"))
    via_deleted = await datasets.upsert(_dataset(organization.id, "via_deleted"))
    await links.replace_for_project("p1", [_link(via_project.id, "p1", organization.id, "n1")])
    await links.replace_for_project("p-deleted", [_link(via_deleted.id, "p-deleted", organization.id, "n2")])
    await connections.touch(via_connection.id, "conn-owner", "r1", NOW)

    owner = CatalogViewer(users["owner"].id, organization.id, ViewerScope.OWN)
    other = CatalogViewer(users["other"].id, organization.id, ViewerScope.OWN)
    admin = CatalogViewer(users["other"].id, organization.id, ViewerScope.ORGANIZATION)

    owner_keys = {hit.dataset.id for hit in (await datasets.search(owner, DatasetSearchQuery())).items}
    assert owner_keys == {via_project.id, via_connection.id}
    assert (await datasets.search(other, DatasetSearchQuery())).items == ()
    admin_page = await datasets.search(admin, DatasetSearchQuery())
    assert {hit.dataset.id for hit in admin_page.items} == {via_project.id, via_connection.id, via_deleted.id}

    project_hit = next(hit for hit in admin_page.items if hit.dataset.id == via_project.id)
    assert (project_hit.reader_count, project_hit.writer_count) == (1, 0)
    deleted_hit = next(hit for hit in admin_page.items if hit.dataset.id == via_deleted.id)
    assert deleted_hit.reader_count == 0, "ссылки удалённых проектов не считаются"

    assert await datasets.get_visible(via_project.id, other) is None
    assert await connections.list_usable_connection_ids(via_connection.id, owner) == ["conn-owner"]
    assert await connections.list_usable_connection_ids(via_connection.id, other) == []


@pytest.mark.asyncio
async def test_replace_links_and_usage_listing(async_test_db_session):
    organization, users = await _seed(async_test_db_session)
    datasets = SQLAlchemyDatasetRepository(async_test_db_session)
    links = SQLAlchemyDatasetLinkRepository(async_test_db_session)
    dataset = await datasets.upsert(_dataset(organization.id, "t"))
    viewer = CatalogViewer(users["owner"].id, organization.id, ViewerScope.OWN)

    await links.replace_for_project("p1", [_link(dataset.id, "p1", organization.id, "n1")])
    await links.replace_for_project(
        "p1",
        [_link(dataset.id, "p1", organization.id, "n2", LinkDirection.WRITE)],
    )

    usage = await links.list_usage(dataset.id, viewer)
    assert [(entry.node_id, entry.direction, entry.project_name) for entry in usage] == [
        ("n2", LinkDirection.WRITE, "P")
    ]
    assert await links.list_usage(dataset.id, viewer, LinkDirection.READ) == []
    assert await links.list_project_ids(dataset.id, viewer) == ["p1"]


@pytest.mark.asyncio
async def test_description_attribution_and_observation_columns_round_trip(async_test_db_session):
    organization, _ = await _seed(async_test_db_session)
    datasets = SQLAlchemyDatasetRepository(async_test_db_session)
    fields = SQLAlchemyDatasetFieldRepository(async_test_db_session)

    dataset = await datasets.upsert(_dataset(organization.id, "t"))
    dataset.description = "table"
    dataset.description_updated_by = "u1"
    dataset.description_updated_at = NOW
    dataset.observed_at_run = NOW
    await datasets.update(dataset)
    await fields.save_many(
        [
            DatasetField(
                id="f1",
                dataset_id=dataset.id,
                name="id",
                status=FieldStatus.OK,
                first_seen_at=NOW,
                last_seen_at=NOW,
                description="pk",
                description_updated_by="u1",
                description_updated_at=NOW,
            )
        ]
    )
    async_test_db_session.expunge_all()

    reloaded = await datasets.get(dataset.id)
    assert (reloaded.description_updated_by, reloaded.description_updated_at, reloaded.observed_at_run) == (
        "u1",
        NOW,
        NOW,
    )
    field = (await fields.list_for_dataset(dataset.id))[0]
    assert (field.description_updated_by, field.description_updated_at) == ("u1", NOW)


@pytest.mark.asyncio
async def test_delete_then_rename_respects_unique_field_name(async_test_db_session):
    organization, _ = await _seed(async_test_db_session)
    datasets = SQLAlchemyDatasetRepository(async_test_db_session)
    fields = SQLAlchemyDatasetFieldRepository(async_test_db_session)
    dataset = await datasets.upsert(_dataset(organization.id, "t"))

    def _field(field_id: str, name: str, status: FieldStatus) -> DatasetField:
        return DatasetField(
            id=field_id, dataset_id=dataset.id, name=name, status=status, first_seen_at=NOW, last_seen_at=NOW
        )

    await fields.save_many([_field("old", "customer_nm", FieldStatus.MISSING), _field("new", "customer_name", FieldStatus.NEW)])
    loaded = {item.id: item for item in await fields.list_for_dataset(dataset.id)}

    await fields.delete("new")
    loaded["old"].name = "customer_name"
    loaded["old"].status = FieldStatus.OK
    await fields.save_many([loaded["old"]])

    remaining = await fields.list_for_dataset(dataset.id)
    assert [(item.id, item.name) for item in remaining] == [("old", "customer_name")]


@pytest.mark.asyncio
async def test_find_dataset_ids_filters_by_node_and_direction(async_test_db_session):
    organization, _ = await _seed(async_test_db_session)
    datasets = SQLAlchemyDatasetRepository(async_test_db_session)
    links = SQLAlchemyDatasetLinkRepository(async_test_db_session)
    read_ds = await datasets.upsert(_dataset(organization.id, "src"))
    write_ds = await datasets.upsert(_dataset(organization.id, "dst"))
    await links.replace_for_project(
        "p1",
        [
            _link(read_ds.id, "p1", organization.id, "reader"),
            _link(write_ds.id, "p1", organization.id, "writer", LinkDirection.WRITE),
        ],
    )

    assert await links.find_dataset_ids("p1", "reader", LinkDirection.READ) == [read_ds.id]
    assert await links.find_dataset_ids("p1", "writer", LinkDirection.READ) == []
    assert await links.find_dataset_ids("p1", "writer", LinkDirection.WRITE) == [write_ds.id]
    assert await links.find_dataset_ids("other", "reader", LinkDirection.READ) == []
