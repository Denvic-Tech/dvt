from datetime import UTC, datetime

import pytest

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.data_catalog.domain import (
    LINEAGE_SCHEMA_VERSION,
    ColumnLineage,
    DatasetField,
    DatasetLink,
    FieldStatus,
    LineageOp,
    LineageRef,
    LinkDirection,
    PortLineage,
    PortStatus,
    ProjectCatalogProjection,
    ProjectionStamp,
    ProjectionStatus,
    ProjectLineage,
    ResolvedVia,
    db_table_locator,
)
from src.modules.data_catalog.domain.entities import Dataset
from src.modules.data_catalog.infra import (
    SQLAlchemyDatasetFieldRepository,
    SQLAlchemyDatasetLinkRepository,
    SQLAlchemyDatasetRepository,
    SQLAlchemyProjectionRepository,
)
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord

NOW = datetime(2026, 10, 20, tzinfo=UTC)


async def _seed(session) -> str:
    organization = OrganizationRecord(name="Org")
    session.add(organization)
    await session.flush()
    user = UserRecord(
        email="owner@example.com", hashed_password="h", auth_provider="email", is_verified=True, is_active=True,
        role=DVTDefaultRoles.USER.value, organization_id=organization.id,
    )
    session.add(user)
    await session.flush()
    session.add_all(
        [
            ProjectRecord(id="p1", name="P1", user_id=user.id, organization_id=organization.id),
            ProjectRecord(id="p2", name="P2", user_id=user.id, organization_id=organization.id),
        ]
    )
    await session.flush()
    return organization.id


def _projection(project_id: str, org_id: str) -> ProjectCatalogProjection:
    return ProjectCatalogProjection(
        project_id=project_id,
        organization_id=org_id,
        stamp=ProjectionStamp(1, "fp", LINEAGE_SCHEMA_VERSION),
        built_at=NOW,
        status=ProjectionStatus.OK,
    )


def _lineage(node_id: str) -> ProjectLineage:
    column = ColumnLineage("id", LineageOp.SOURCE, (LineageRef.dataset_field("ds-t", "f1"),), origin=LineageRef.dataset_field("ds-t", "f1"))
    return ProjectLineage(ports=(PortLineage(node_id, "ReadTableFromDBV3", "output", PortStatus.RESOLVED, (column,)),))


@pytest.mark.asyncio
async def test_lineage_document_is_saved_loaded_and_cleared_separately_from_the_stamp(async_test_db_session):
    org_id = await _seed(async_test_db_session)
    repo = SQLAlchemyProjectionRepository(async_test_db_session)
    await repo.save(_projection("p1", org_id))
    await repo.save(_projection("p2", org_id))

    await repo.save_lineage("p1", _lineage("r1"))
    await repo.save_lineage("p2", _lineage("r2"))

    loaded = await repo.load_lineage_many(["p1", "p2", "p3"])
    assert set(loaded) == {"p1", "p2"}
    assert loaded["p1"].ports[0].node_id == "r1"
    assert (await repo.load_lineage("p2")).ports[0].columns[0].origin.key == "ds:ds-t:f1"
    assert (await repo.get("p1")).stamp.lineage_schema_version == LINEAGE_SCHEMA_VERSION

    await repo.save_lineage("p1", None)
    assert await repo.load_lineage("p1") is None
    assert (await repo.get("p1")) is not None, "clearing lineage keeps the projection row"


@pytest.mark.asyncio
async def test_mark_stale_for_dataset_resets_only_consumer_projections(async_test_db_session):
    org_id = await _seed(async_test_db_session)
    projections = SQLAlchemyProjectionRepository(async_test_db_session)
    datasets = SQLAlchemyDatasetRepository(async_test_db_session)
    links = SQLAlchemyDatasetLinkRepository(async_test_db_session)
    await projections.save(_projection("p1", org_id))
    await projections.save(_projection("p2", org_id))
    dataset = await datasets.upsert(
        Dataset(id="ds-t", organization_id=org_id, locator=db_table_locator("postgresql", "db", 5432, "main", "public", "t"), physical_key="k", created_at=NOW, updated_at=NOW)
    )
    await links.replace_for_project(
        "p1", [DatasetLink("l1", dataset.id, "p1", org_id, "r", "ReadTableFromDBV3", LinkDirection.READ, ResolvedVia.CONST, 1, NOW, NOW)]
    )

    assert await projections.mark_stale_for_dataset(dataset.id) == 1
    assert (await projections.get("p1")).stamp.lineage_schema_version == 0
    assert (await projections.get("p2")).stamp.lineage_schema_version == LINEAGE_SCHEMA_VERSION
    assert await projections.mark_stale_for_dataset(dataset.id) == 0, "already stale rows are not counted again"


@pytest.mark.asyncio
async def test_list_for_datasets_groups_fields_and_keeps_requested_keys(async_test_db_session):
    org_id = await _seed(async_test_db_session)
    datasets = SQLAlchemyDatasetRepository(async_test_db_session)
    fields = SQLAlchemyDatasetFieldRepository(async_test_db_session)
    for table in ("a", "b"):
        await datasets.upsert(
            Dataset(id=f"ds-{table}", organization_id=org_id, locator=db_table_locator("postgresql", "db", 5432, "main", "public", table), physical_key=f"k-{table}", created_at=NOW, updated_at=NOW)
        )
    await fields.save_many(
        [
            DatasetField(id="fa2", dataset_id="ds-a", name="z", status=FieldStatus.OK, first_seen_at=NOW, last_seen_at=NOW, ordinal=2),
            DatasetField(id="fa1", dataset_id="ds-a", name="y", status=FieldStatus.OK, first_seen_at=NOW, last_seen_at=NOW, ordinal=1),
            DatasetField(id="fb1", dataset_id="ds-b", name="x", status=FieldStatus.OK, first_seen_at=NOW, last_seen_at=NOW),
        ]
    )

    grouped = await fields.list_for_datasets(["ds-a", "ds-b", "ds-none"])

    assert [item.name for item in grouped["ds-a"]] == ["y", "z"]
    assert [item.name for item in grouped["ds-b"]] == ["x"]
    assert grouped["ds-none"] == []
