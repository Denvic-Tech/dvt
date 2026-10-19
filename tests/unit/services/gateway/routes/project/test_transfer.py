"""Gateway wiring of project export/import: request parsing, archive streaming, upload limits."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field

import pytest
import sqlalchemy as sa
from fastapi import UploadFile
from usrak.core.security import hash_password

from services.gateway.routes.impl.project import transfer as transfer_impl

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.project_transfer.domain.entities import BundleConnection
from src.modules.project_transfer.domain.exceptions import BundleTooLargeError, InvalidBundleError
from src.modules.project_transfer.domain.value_objects import (
    ExistingConnection,
    InstanceInfo,
    NodeTypeInfo,
)
from src.modules.project_transfer.infra.schemas import ExportRequestSchema
from src.modules.user.infra.db_models import UserRecord


@dataclass
class FakeConnections:
    ids: set[str] = field(default_factory=set)

    async def describe(self, connection_id, *, actor, ref):
        if connection_id not in self.ids:
            return None
        return BundleConnection(ref=ref, name="pg", kind="sql", type="postgresql")

    async def read_secrets(self, connection_id, *, actor):
        return {"password": "pw"} if connection_id in self.ids else None

    async def exists(self, connection_id, *, actor):
        return connection_id in self.ids

    async def find_candidates(self, connection, *, actor):
        return [ExistingConnection(id=cid, name="pg", kind="sql", type="postgresql") for cid in sorted(self.ids)]

    async def create(self, connection, *, secrets, actor):
        self.ids.add("created")
        return "created"


class FakeNodeTypes:
    async def describe(self, node_name):
        return NodeTypeInfo(
            name=node_name,
            known=True,
            connection_input_names=("connection_id",) if node_name == "GetExistDBConnection" else (),
        )


class FakeInstance:
    def get(self):
        return InstanceInfo(instance_id="test-instance", version="0.0.0-test")


class FakeSchedulerClient:
    def __init__(self) -> None:
        self.unscheduled: list[str] = []
        self.scheduled: list[dict] = []

    async def unschedule_project(self, project_id):
        self.unscheduled.append(project_id)

    async def schedule_project(self, data):
        self.scheduled.append(data)


@pytest.fixture
async def admin_user(async_db_session) -> UserRecord:
    organization = OrganizationRecord(name="Transfer route org")
    user = UserRecord(
        email="transfer-admin@example.com",
        hashed_password=hash_password("Password123"),
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.ADMIN.value,
        organization_id=organization.id,
    )
    async_db_session.add(organization)
    async_db_session.add(user)
    await async_db_session.commit()
    return user


@pytest.fixture
def fake_gateways(monkeypatch):
    connections = FakeConnections(ids={"conn-1"})
    monkeypatch.setattr(transfer_impl, "_connections_gateway", lambda user: connections)
    monkeypatch.setattr(transfer_impl, "_node_catalog", lambda session: FakeNodeTypes())
    monkeypatch.setattr(transfer_impl, "_instance_info", FakeInstance)
    return connections


async def _seed_project(session, user: UserRecord) -> ProjectRecord:
    project = ProjectRecord(name="Routed", user_id=user.id, organization_id=user.organization_id)
    session.add(project)
    await session.flush()
    session.add(
        GraphNodeRecord(
            ui_id="n1",
            type="custom",
            position_x=0,
            position_y=0,
            name="GetExistDBConnection",
            display_name="DB",
            input_values={"connection_id": {"__dvt_type": "const", "value": "conn-1"}},
            project_id=project.id,
            user_id=user.id,
            organization_id=user.organization_id,
        )
    )
    await session.commit()
    return project


async def _collect(response) -> bytes:
    chunks = [chunk async for chunk in response.body_iterator]
    return b"".join(chunk if isinstance(chunk, bytes) else chunk.encode() for chunk in chunks)


def _upload(data: bytes, name="bundle.dvtpkg") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


async def test_export_then_preview_then_import(async_db_session, admin_user, fake_gateways):
    project = await _seed_project(async_db_session, admin_user)
    scheduler = FakeSchedulerClient()

    response = await transfer_impl.export_route_impl(
        data=ExportRequestSchema(project_ids=[project.id], include_schedule=True, disable_schedule_after_export=True),
        session=async_db_session,
        user=admin_user,
        scheduler_client=scheduler,
    )

    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"].startswith('attachment; filename="Routed.dvtpkg"')
    assert transfer_impl.EXPORT_WARNINGS_HEADER not in response.headers
    archive = await _collect(response)
    assert archive[:2] == b"PK"
    assert scheduler.unscheduled == []  # the project had no active schedule

    preview = await transfer_impl.preview_import_route_impl(
        file=_upload(archive),
        payload=json.dumps({"mode": "create"}),
        session=async_db_session,
        user=admin_user,
    )
    assert preview.projects[0].name == "Routed"
    assert preview.connections[0].candidates[0].id == "conn-1"
    assert preview.can_manage_schedules is True

    result = await transfer_impl.import_route_impl(
        file=_upload(archive),
        payload=json.dumps(
            {
                "mode": "create",
                "connections": {"connection-1": {"action": "use_existing", "connection_id": "conn-1"}},
            }
        ),
        session=async_db_session,
        user=admin_user,
        scheduler_client=scheduler,
    )

    imported_id = result.project_ids["project-1"]
    assert imported_id != project.id
    node = (
        await async_db_session.execute(sa.select(GraphNodeRecord).where(GraphNodeRecord.project_id == imported_id))
    ).scalar_one()
    assert node.input_values["connection_id"]["value"] == "conn-1"


async def test_import_rejects_bad_payload_empty_and_oversized_uploads(async_db_session, admin_user, fake_gateways, monkeypatch):
    with pytest.raises(InvalidBundleError):
        await transfer_impl.preview_import_route_impl(
            file=_upload(b"PK..."), payload="{not json", session=async_db_session, user=admin_user
        )
    with pytest.raises(InvalidBundleError):
        await transfer_impl.preview_import_route_impl(
            file=_upload(b""), payload=None, session=async_db_session, user=admin_user
        )

    monkeypatch.setattr(transfer_impl.config.OTHER, "PROJECT_TRANSFER_BUNDLE_MAX_SIZE_BYTES", 4)
    with pytest.raises(BundleTooLargeError):
        await transfer_impl.preview_import_route_impl(
            file=_upload(b"PK\x03\x04 too big"), payload=None, session=async_db_session, user=admin_user
        )


async def test_export_warnings_header_lists_schedule_outcomes(async_db_session, admin_user, fake_gateways, monkeypatch):
    project = await _seed_project(async_db_session, admin_user)

    class FailingScheduler(FakeSchedulerClient):
        async def unschedule_project(self, project_id):
            raise RuntimeError("scheduler down")

    from src.modules.project_transfer.domain.entities import ScheduleSnapshot
    from src.modules.project_transfer.infra.gateways import schedule as schedule_gateway

    async def fake_read(self, project_id):
        return ScheduleSnapshot(cron="0 0 * * *", mode="full")

    monkeypatch.setattr(schedule_gateway.ProjectSchedulerGateway, "read", fake_read)

    response = await transfer_impl.export_route_impl(
        data=ExportRequestSchema(project_ids=[project.id], include_schedule=True, disable_schedule_after_export=True),
        session=async_db_session,
        user=admin_user,
        scheduler_client=FailingScheduler(),
    )

    warnings = json.loads(response.headers[transfer_impl.EXPORT_WARNINGS_HEADER])
    assert warnings[0]["code"] == "schedule_disable_failed"
    await _collect(response)
