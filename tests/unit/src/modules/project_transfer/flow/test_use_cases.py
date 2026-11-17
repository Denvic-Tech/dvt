"""Export and import use cases against the SQLite schema with fake external gateways."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import sqlalchemy as sa
from usrak.core.security import hash_password

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.file_storage.infra.db_models import DVTServiceFileObjectRecord
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)
from src.modules.project.infra.db_models import (
    ProjectFolderRecord,
    ProjectRecord,
    ProjectScheduleRecord,
)
from src.modules.project_transfer.domain.entities import BundleConnection, ScheduleSnapshot
from src.modules.project_transfer.domain.exceptions import (
    FolderDepthExceededError,
    InvalidConnectionDecisionError,
    InvalidImportTargetError,
    InvalidPassphraseError,
)
from src.modules.project_transfer.domain.types import (
    ConflictDecision,
    ConnectionDecisionAction,
    ImportMode,
    MergeStrategy,
    TransferWarningCode,
)
from src.modules.project_transfer.domain.value_objects import (
    ConnectionDecision,
    ExistingConnection,
    ExportOptions,
    ExportSelection,
    ImportDecisions,
    ImportTarget,
    InstanceInfo,
    NodeTypeInfo,
    ScheduleDecision,
    TransferActor,
    VariableDecision,
)
from src.modules.project_transfer.flow.exceptions import ImportTargetNotFoundError
from src.modules.project_transfer.flow.use_cases import (
    DisableExportedSchedulesUseCase,
    ExportBundleUseCase,
    ImportBundleUseCase,
    PreviewImportUseCase,
)
from src.modules.project_transfer.infra.crypto import PassphraseSecretsCipher
from src.modules.project_transfer.infra.repositories import (
    SQLProjectTransferReadRepository,
    SQLProjectTransferWriteRepository,
)
from src.modules.project_transfer.infra.serialization import read_bundle, write_bundle
from src.modules.user.infra.db_models import UserRecord

# --- fakes -------------------------------------------------------------------


@dataclass
class FakeConnections:
    known: dict[str, BundleConnection] = field(default_factory=dict)
    secrets: dict[str, dict[str, Any]] = field(default_factory=dict)
    created: list[tuple[BundleConnection, dict[str, Any]]] = field(default_factory=list)
    fail_create: bool = False

    async def describe(self, connection_id, *, actor, ref):
        known = self.known.get(connection_id)
        if known is None:
            return None
        return BundleConnection(
            ref=ref,
            name=known.name,
            kind=known.kind,
            type=known.type,
            driver=known.driver,
            properties=dict(known.properties),
            labels=dict(known.labels),
        )

    async def read_secrets(self, connection_id, *, actor):
        return self.secrets.get(connection_id)

    async def exists(self, connection_id, *, actor):
        return connection_id in self.known

    async def find_candidates(self, connection, *, actor):
        return [
            ExistingConnection(id=cid, name=c.name, kind=c.kind, type=c.type)
            for cid, c in self.known.items()
            if c.name == connection.name and c.type == connection.type
        ]

    async def create(self, connection, *, secrets, actor):
        if self.fail_create:
            raise RuntimeError("boom")
        new_id = f"created-{len(self.created) + 1}"
        self.created.append((connection, dict(secrets)))
        self.known[new_id] = connection
        return new_id


@dataclass
class FakeNodeTypes:
    connection_inputs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unknown: set[str] = field(default_factory=set)
    extension_nodes: dict[str, tuple[str, bool]] = field(default_factory=dict)

    async def describe(self, node_name):
        if node_name in self.unknown:
            return NodeTypeInfo(name=node_name, known=False)
        extension = self.extension_nodes.get(node_name)
        return NodeTypeInfo(
            name=node_name,
            known=True,
            extension_name=extension[0] if extension else None,
            extension_available=extension[1] if extension else True,
            connection_input_names=self.connection_inputs.get(node_name, ()),
        )


@dataclass
class FakeSchedules:
    snapshots: dict[str, ScheduleSnapshot] = field(default_factory=dict)
    disabled: list[str] = field(default_factory=list)
    applied: list[tuple[str, ScheduleSnapshot, bool]] = field(default_factory=list)
    fail: bool = False

    async def read(self, project_id):
        return self.snapshots.get(project_id)

    async def disable(self, project_id):
        if self.fail:
            raise RuntimeError("scheduler down")
        self.disabled.append(project_id)

    async def apply(self, project_id, schedule, *, enabled, actor, replace_existing):
        if self.fail:
            raise RuntimeError("scheduler down")
        self.applied.append((project_id, schedule, enabled))


class FakeInstance:
    def get(self):
        return InstanceInfo(instance_id="instance-A", version="9.9.9")


# --- fixtures ----------------------------------------------------------------


def _const(value):
    return {"__dvt_type": "const", "value": value}


@pytest.fixture
async def org_and_users(async_test_db_session):
    organization = OrganizationRecord(name="Transfer org")
    async_test_db_session.add(organization)
    await async_test_db_session.flush()
    users = {}
    for role, email in ((DVTDefaultRoles.USER, "owner@example.com"), (DVTDefaultRoles.ADMIN, "admin@example.com")):
        user = UserRecord(
            email=email,
            hashed_password=hash_password("Password123"),
            auth_provider="email",
            is_verified=True,
            is_active=True,
            role=role.value,
            organization_id=organization.id,
        )
        async_test_db_session.add(user)
        users[role] = user
    await async_test_db_session.commit()
    return organization, users[DVTDefaultRoles.USER], users[DVTDefaultRoles.ADMIN]


def _actor(user: UserRecord, *, admin: bool = False) -> TransferActor:
    return TransferActor(user_id=user.id, organization_id=user.organization_id, is_admin=admin)


async def _seed_project(session, *, owner: UserRecord, folder_id: str | None = None, name="Source") -> ProjectRecord:
    project = ProjectRecord(
        name=name,
        user_id=owner.id,
        organization_id=owner.organization_id,
        folder_id=folder_id,
        store_enabled=True,
        ttl_time=120,
        workers_count=3,
        variables={"limit": {"type": "int", "value": 10, "is_list_type": False}},
    )
    session.add(project)
    await session.flush()
    common = {"project_id": project.id, "user_id": owner.id, "organization_id": owner.organization_id}
    session.add(
        SubgraphRecord(
            ui_id="sub-1", type="subgraph", position_x=0, position_y=0, name="Group", display_name="Group", **common
        )
    )
    session.add(
        GraphNodeRecord(
            ui_id="n-conn",
            type="custom",
            position_x=0,
            position_y=0,
            name="GetExistDBConnection",
            display_name="DB",
            input_values={"connection_id": _const("conn-src")},
            subgraph_id="sub-1",
            **common,
        )
    )
    session.add(
        GraphNodeRecord(
            ui_id="n-csv",
            type="custom",
            position_x=5,
            position_y=5,
            name="LoadCSV",
            display_name="CSV",
            show_variables_io=True,
            input_values={
                "connection": _const(
                    {
                        "id": f"dvt-service-files:{project.id}:n-csv:file",
                        "type": "dvt_service_files",
                        "kind": "file",
                        "properties": {
                            "organization_id": owner.organization_id,
                            "project_id": project.id,
                            "root_prefix": "node-inputs/n-csv/file",
                        },
                        "secrets": {},
                    }
                ),
                "path": _const("data.csv"),
            },
            **common,
        )
    )
    session.add(
        GraphEdgeRecord(
            ui_id="e-1", type="default", source="n-conn", target="n-csv", source_handle="o", target_handle="i", **common
        )
    )
    session.add(
        DVTServiceFileObjectRecord(
            organization_id=owner.organization_id,
            project_id=project.id,
            parent_path="node-inputs/n-csv/file",
            name="data.csv",
            content=b"id\n1\n",
            content_type="text/csv",
            size=5,
            sha256="x",
        )
    )
    await session.commit()
    return project


def _export_use_case(session, connections, node_types, schedules):
    return ExportBundleUseCase(
        repository=SQLProjectTransferReadRepository(session),
        connections=connections,
        node_types=node_types,
        schedules=schedules,
        cipher=PassphraseSecretsCipher(),
        instance_info=FakeInstance(),
    )


def _import_use_case(session, connections, node_types, schedules):
    return ImportBundleUseCase(
        repository=SQLProjectTransferWriteRepository(session),
        connections=connections,
        node_types=node_types,
        schedules=schedules,
        cipher=PassphraseSecretsCipher(),
    )


def _fakes():
    connections = FakeConnections(
        known={"conn-src": BundleConnection(ref="", name="warehouse", kind="sql", type="postgresql", properties={"host": "db"})},
        secrets={"conn-src": {"password": "pw"}},
    )
    node_types = FakeNodeTypes(connection_inputs={"GetExistDBConnection": ("connection_id",)})
    return connections, node_types, FakeSchedules()


# --- export ------------------------------------------------------------------


async def test_export_single_project_with_everything(async_test_db_session, org_and_users):
    _org, owner, _admin = org_and_users
    project = await _seed_project(async_test_db_session, owner=owner)
    connections, node_types, schedules = _fakes()
    schedules.snapshots[project.id] = ScheduleSnapshot(cron="0 1 * * *", mode="full")

    result = await _export_use_case(async_test_db_session, connections, node_types, schedules).execute(
        ExportSelection(project_ids=(project.id,)),
        ExportOptions(include_variables=True, include_secrets=True, include_schedule=True, passphrase="passphrase1"),
        actor=_actor(owner),
    )

    bundle = result.bundle
    assert result.file_name == "Source.dvtpkg"
    assert result.schedule_project_ids == [project.id]
    assert bundle.manifest.source_instance_id == "instance-A"
    assert [item.name for item in bundle.manifest.required_node_types] == ["GetExistDBConnection", "LoadCSV"]
    assert bundle.manifest.has_secrets is True and bundle.encrypted_secrets

    [exported] = bundle.projects
    assert exported.meta.name == "Source" and exported.meta.ttl_time == 120
    assert exported.variables == {"limit": {"type": "int", "value": 10, "is_list_type": False}}
    assert exported.schedule.cron == "0 1 * * *"
    assert len(exported.graph.nodes) == 2 and len(exported.graph.edges) == 1 and len(exported.graph.subgraphs) == 1
    assert exported.files[0].storage_path == "node-inputs/n-csv/file/data.csv" and exported.files[0].content == b"id\n1\n"
    assert [(b.node_ui_id, b.input_name, b.connection_ref) for b in exported.connection_bindings] == [
        ("n-conn", "connection_id", "connection-1")
    ]
    [connection] = bundle.connections
    assert (connection.name, connection.type, connection.properties) == ("warehouse", "postgresql", {"host": "db"})
    assert PassphraseSecretsCipher().decrypt(bundle.encrypted_secrets, passphrase="passphrase1") == {
        "connection-1": {"password": "pw"}
    }

    # The archive round-trips.
    restored = read_bundle(write_bundle(bundle).read(), max_uncompressed_bytes=10_000_000)
    assert restored.projects[0].connection_bindings == exported.connection_bindings


async def test_export_folder_subtree_and_inaccessible_connection(async_test_db_session, org_and_users):
    _org, owner, _admin = org_and_users
    root = ProjectFolderRecord(name="Root", user_id=owner.id, organization_id=owner.organization_id)
    async_test_db_session.add(root)
    await async_test_db_session.flush()
    child = ProjectFolderRecord(name="Child", parent_id=root.id, user_id=owner.id, organization_id=owner.organization_id)
    async_test_db_session.add(child)
    await async_test_db_session.flush()
    in_root = await _seed_project(async_test_db_session, owner=owner, folder_id=root.id, name="In root")
    in_child = await _seed_project(async_test_db_session, owner=owner, folder_id=child.id, name="In child")
    connections, node_types, schedules = _fakes()
    connections.known.clear()

    result = await _export_use_case(async_test_db_session, connections, node_types, schedules).execute(
        ExportSelection(folder_ids=(root.id,)),
        ExportOptions(include_files=False),
        actor=_actor(owner),
    )

    bundle = result.bundle
    assert result.file_name == "Root.dvtpkg"
    folders = {folder.name: folder for folder in bundle.folders}
    assert folders["Root"].parent_ref is None
    assert folders["Child"].parent_ref == folders["Root"].ref
    by_name = {project.meta.name: project for project in bundle.projects}
    assert by_name["In root"].folder_ref == folders["Root"].ref
    assert by_name["In child"].folder_ref == folders["Child"].ref
    assert {in_root.id, in_child.id} and all(project.files == [] for project in bundle.projects)
    assert all(project.variables is None for project in bundle.projects)
    assert bundle.connections[0].inaccessible is True
    assert {w.code for w in result.warnings} == {TransferWarningCode.CONNECTION_INACCESSIBLE}


async def test_export_requires_passphrase_for_secrets_and_scopes_access(async_test_db_session, org_and_users):
    _org, owner, admin = org_and_users
    project = await _seed_project(async_test_db_session, owner=owner)
    connections, node_types, schedules = _fakes()
    use_case = _export_use_case(async_test_db_session, connections, node_types, schedules)

    from src.modules.project_transfer.domain.exceptions import SecretsPassphraseRequiredError
    from src.modules.project_transfer.flow.exceptions import ExportSelectionNotFoundError

    with pytest.raises(SecretsPassphraseRequiredError):
        await use_case.execute(
            ExportSelection(project_ids=(project.id,)), ExportOptions(include_secrets=True), actor=_actor(owner)
        )

    stranger = TransferActor(user_id="someone-else", organization_id=owner.organization_id)
    with pytest.raises(ExportSelectionNotFoundError):
        await use_case.execute(ExportSelection(project_ids=(project.id,)), ExportOptions(), actor=stranger)

    # Organization admins see every project of their organization.
    result = await use_case.execute(
        ExportSelection(project_ids=(project.id,)), ExportOptions(), actor=_actor(admin, admin=True)
    )
    assert len(result.bundle.projects) == 1


async def test_disable_exported_schedules_requires_admin(async_test_db_session, org_and_users):
    _org, owner, admin = org_and_users
    schedules = FakeSchedules()

    warnings = await DisableExportedSchedulesUseCase(schedules=schedules).execute(["p1"], actor=_actor(owner))
    assert [w.code for w in warnings] == [TransferWarningCode.SCHEDULE_FORBIDDEN]
    assert schedules.disabled == []

    assert await DisableExportedSchedulesUseCase(schedules=schedules).execute(["p1"], actor=_actor(admin, admin=True)) == []
    assert schedules.disabled == ["p1"]

    schedules.fail = True
    warnings = await DisableExportedSchedulesUseCase(schedules=schedules).execute(["p2"], actor=_actor(admin, admin=True))
    assert [w.code for w in warnings] == [TransferWarningCode.SCHEDULE_DISABLE_FAILED]


# --- import: create -----------------------------------------------------------


async def _exported_bundle(session, owner, *, connections, node_types, schedules, **options):
    project = await _seed_project(session, owner=owner)
    result = await _export_use_case(session, connections, node_types, schedules).execute(
        ExportSelection(project_ids=(project.id,)),
        ExportOptions(include_variables=True, **options),
        actor=_actor(owner),
    )
    # Go through the archive so the import sees exactly what a client would upload.
    return project, read_bundle(write_bundle(result.bundle).read(), max_uncompressed_bytes=10_000_000)


async def test_import_create_project_with_existing_connection(async_test_db_session, org_and_users):
    _org, owner, admin = org_and_users
    connections, node_types, schedules = _fakes()
    source, bundle = await _exported_bundle(
        async_test_db_session, owner, connections=connections, node_types=node_types, schedules=schedules
    )
    folder = ProjectFolderRecord(name="Target", user_id=admin.id, organization_id=admin.organization_id)
    async_test_db_session.add(folder)
    await async_test_db_session.commit()

    result = await _import_use_case(async_test_db_session, connections, node_types, schedules).execute(
        bundle,
        ImportTarget(mode=ImportMode.CREATE, folder_id=folder.id),
        ImportDecisions(
            connections={
                "connection-1": ConnectionDecision(ConnectionDecisionAction.USE_EXISTING, connection_id="conn-src")
            }
        ),
        actor=_actor(admin, admin=True),
    )

    new_id = result.project_ids["project-1"]
    assert new_id != source.id
    assert result.connection_ids == {"connection-1": "conn-src"} and result.skipped_connection_refs == []
    assert result.warnings == []

    created = await async_test_db_session.get(ProjectRecord, new_id)
    assert (created.name, created.folder_id, created.user_id, created.ttl_time) == ("Source", folder.id, admin.id, 120)
    assert created.variables == {"limit": {"type": "int", "value": 10, "is_list_type": False}}

    nodes = (await async_test_db_session.execute(sa.select(GraphNodeRecord).where(GraphNodeRecord.project_id == new_id))).scalars().all()
    edges = (await async_test_db_session.execute(sa.select(GraphEdgeRecord).where(GraphEdgeRecord.project_id == new_id))).scalars().all()
    subgraphs = (await async_test_db_session.execute(sa.select(SubgraphRecord).where(SubgraphRecord.project_id == new_id))).scalars().all()
    assert len(nodes) == 2 and len(edges) == 1 and len(subgraphs) == 1
    by_name = {node.name: node for node in nodes}
    assert by_name["GetExistDBConnection"].input_values["connection_id"] == _const("conn-src")
    assert by_name["GetExistDBConnection"].subgraph_id == subgraphs[0].ui_id
    assert by_name["LoadCSV"].show_variables_io is True
    assert edges[0].source == by_name["GetExistDBConnection"].ui_id and edges[0].target == by_name["LoadCSV"].ui_id

    csv_node = by_name["LoadCSV"]
    service_connection = csv_node.input_values["connection"]["value"]
    assert service_connection["properties"]["project_id"] == new_id
    files = (
        await async_test_db_session.execute(
            sa.select(DVTServiceFileObjectRecord).where(DVTServiceFileObjectRecord.project_id == new_id)
        )
    ).scalars().all()
    assert [(f.parent_path, f.name, f.content) for f in files] == [
        (service_connection["properties"]["root_prefix"], "data.csv", b"id\n1\n")
    ]


async def test_import_create_with_new_connection_from_bundle_secrets(async_test_db_session, org_and_users):
    _org, owner, _admin = org_and_users
    connections, node_types, schedules = _fakes()
    _source, bundle = await _exported_bundle(
        async_test_db_session,
        owner,
        connections=connections,
        node_types=node_types,
        schedules=schedules,
        include_secrets=True,
        passphrase="passphrase1",
    )
    target_connections = FakeConnections()

    with pytest.raises(InvalidPassphraseError):
        await _import_use_case(async_test_db_session, target_connections, node_types, schedules).execute(
            bundle,
            ImportTarget(mode=ImportMode.CREATE),
            ImportDecisions(
                connections={"connection-1": ConnectionDecision(ConnectionDecisionAction.CREATE)},
                passphrase="wrong-passphrase",
            ),
            actor=_actor(owner),
        )

    result = await _import_use_case(async_test_db_session, target_connections, node_types, schedules).execute(
        bundle,
        ImportTarget(mode=ImportMode.CREATE),
        ImportDecisions(
            connections={"connection-1": ConnectionDecision(ConnectionDecisionAction.CREATE)},
            passphrase="passphrase1",
        ),
        actor=_actor(owner),
    )

    assert result.connection_ids == {"connection-1": "created-1"}
    [(created_connection, created_secrets)] = target_connections.created
    assert created_connection.name == "warehouse" and created_secrets == {"password": "pw"}
    node = (
        await async_test_db_session.execute(
            sa.select(GraphNodeRecord).where(
                GraphNodeRecord.project_id == result.project_ids["project-1"],
                GraphNodeRecord.name == "GetExistDBConnection",
            )
        )
    ).scalar_one()
    assert node.input_values["connection_id"] == _const("created-1")


async def test_import_skipped_connection_and_failed_create_become_warnings(async_test_db_session, org_and_users):
    _org, owner, _admin = org_and_users
    connections, node_types, schedules = _fakes()
    _source, bundle = await _exported_bundle(
        async_test_db_session, owner, connections=connections, node_types=node_types, schedules=schedules
    )

    result = await _import_use_case(async_test_db_session, FakeConnections(), node_types, schedules).execute(
        bundle, ImportTarget(mode=ImportMode.CREATE), ImportDecisions(), actor=_actor(owner)
    )
    assert result.skipped_connection_refs == ["connection-1"]
    assert [w.code for w in result.warnings] == [TransferWarningCode.CONNECTION_SKIPPED]

    failing = FakeConnections(fail_create=True)
    result = await _import_use_case(async_test_db_session, failing, node_types, schedules).execute(
        bundle,
        ImportTarget(mode=ImportMode.CREATE),
        ImportDecisions(connections={"connection-1": ConnectionDecision(ConnectionDecisionAction.CREATE)}),
        actor=_actor(owner),
    )
    assert [w.code for w in result.warnings] == [TransferWarningCode.CONNECTION_CREATE_FAILED]

    with pytest.raises(InvalidConnectionDecisionError):
        await _import_use_case(async_test_db_session, FakeConnections(), node_types, schedules).execute(
            bundle,
            ImportTarget(mode=ImportMode.CREATE),
            ImportDecisions(
                connections={"connection-1": ConnectionDecision(ConnectionDecisionAction.USE_EXISTING, connection_id="nope")}
            ),
            actor=_actor(owner),
        )


async def test_import_folders_tree_and_depth_limit(async_test_db_session, org_and_users):
    _org, owner, _admin = org_and_users
    connections, node_types, schedules = _fakes()
    root = ProjectFolderRecord(name="Root", user_id=owner.id, organization_id=owner.organization_id)
    async_test_db_session.add(root)
    await async_test_db_session.flush()
    child = ProjectFolderRecord(name="Child", parent_id=root.id, user_id=owner.id, organization_id=owner.organization_id)
    async_test_db_session.add(child)
    await async_test_db_session.flush()
    await _seed_project(async_test_db_session, owner=owner, folder_id=child.id, name="Deep")
    export = await _export_use_case(async_test_db_session, connections, node_types, schedules).execute(
        ExportSelection(folder_ids=(root.id,)), ExportOptions(), actor=_actor(owner)
    )
    bundle = read_bundle(write_bundle(export.bundle).read(), max_uncompressed_bytes=10_000_000)

    result = await _import_use_case(async_test_db_session, connections, node_types, schedules).execute(
        bundle, ImportTarget(mode=ImportMode.CREATE), ImportDecisions(), actor=_actor(owner)
    )

    folders = {
        folder.id: folder
        for folder in (await async_test_db_session.execute(sa.select(ProjectFolderRecord))).scalars().all()
    }
    bundle_folders = {folder.name: folder for folder in bundle.folders}
    new_root = folders[result.folder_ids[bundle_folders["Root"].ref]]
    new_child = folders[result.folder_ids[bundle_folders["Child"].ref]]
    assert (new_root.name, new_root.parent_id) == ("Root", None)
    assert (new_child.name, new_child.parent_id) == ("Child", new_root.id)
    project = await async_test_db_session.get(ProjectRecord, result.project_ids["project-1"])
    assert project.folder_id == new_child.id

    # Depth 2 bundle under a depth-4 folder exceeds the maximum of 5.
    deep_ids = [new_child.id]
    for name in ("L3", "L4"):
        deeper = ProjectFolderRecord(name=name, parent_id=deep_ids[-1], user_id=owner.id, organization_id=owner.organization_id)
        async_test_db_session.add(deeper)
        await async_test_db_session.flush()
        deep_ids.append(deeper.id)
    await async_test_db_session.commit()
    with pytest.raises(FolderDepthExceededError):
        await PreviewImportUseCase(
            repository=SQLProjectTransferWriteRepository(async_test_db_session),
            connections=connections,
            node_types=node_types,
        ).execute(bundle, ImportTarget(mode=ImportMode.CREATE, folder_id=deep_ids[-1]), actor=_actor(owner))
    with pytest.raises(ImportTargetNotFoundError):
        await PreviewImportUseCase(
            repository=SQLProjectTransferWriteRepository(async_test_db_session),
            connections=connections,
            node_types=node_types,
        ).execute(bundle, ImportTarget(mode=ImportMode.CREATE, folder_id="missing"), actor=_actor(owner))


# --- import: merge ------------------------------------------------------------


async def test_import_merge_append_keeps_existing_graph_and_resolves_variables(async_test_db_session, org_and_users):
    _org, owner, _admin = org_and_users
    connections, node_types, schedules = _fakes()
    _source, bundle = await _exported_bundle(
        async_test_db_session, owner, connections=connections, node_types=node_types, schedules=schedules
    )
    target = await _seed_project(async_test_db_session, owner=owner, name="Target")
    target.variables = {
        "limit": {"type": "int", "value": 99, "is_list_type": False},
        "keep": {"type": "str", "value": "me", "is_list_type": False},
    }
    async_test_db_session.add(target)
    await async_test_db_session.commit()

    result = await _import_use_case(async_test_db_session, connections, node_types, schedules).execute(
        bundle,
        ImportTarget(mode=ImportMode.MERGE, project_id=target.id, merge_strategy=MergeStrategy.APPEND),
        ImportDecisions(
            connections={
                "connection-1": ConnectionDecision(ConnectionDecisionAction.USE_EXISTING, connection_id="conn-src")
            },
            variables={"project-1": {"extra": VariableDecision(value={"type": "str", "value": "new", "is_list_type": False})}},
        ),
        actor=_actor(owner),
    )

    assert result.project_ids == {"project-1": target.id}
    assert [w.code for w in result.warnings] == [TransferWarningCode.VARIABLE_CONFLICT]
    nodes = (await async_test_db_session.execute(sa.select(GraphNodeRecord).where(GraphNodeRecord.project_id == target.id))).scalars().all()
    assert len(nodes) == 4
    assert {"n-conn", "n-csv"} < {node.ui_id for node in nodes}
    await async_test_db_session.refresh(target)
    assert target.variables["limit"]["value"] == 99
    assert target.variables["keep"]["value"] == "me"
    assert target.variables["extra"]["value"] == "new"
    assert target.graph_revision == 1
    assert len(target.dirty_node_ids) == 2


async def test_import_merge_replace_clears_old_graph_and_files(async_test_db_session, org_and_users):
    _org, owner, _admin = org_and_users
    connections, node_types, schedules = _fakes()
    _source, bundle = await _exported_bundle(
        async_test_db_session, owner, connections=connections, node_types=node_types, schedules=schedules
    )
    target = await _seed_project(async_test_db_session, owner=owner, name="Target")

    result = await _import_use_case(async_test_db_session, connections, node_types, schedules).execute(
        bundle,
        ImportTarget(mode=ImportMode.MERGE, project_id=target.id, merge_strategy=MergeStrategy.REPLACE),
        ImportDecisions(
            connections={
                "connection-1": ConnectionDecision(ConnectionDecisionAction.USE_EXISTING, connection_id="conn-src")
            },
            variables={"project-1": {"limit": VariableDecision(conflict=ConflictDecision.OVERWRITE)}},
        ),
        actor=_actor(owner),
    )

    nodes = (await async_test_db_session.execute(sa.select(GraphNodeRecord).where(GraphNodeRecord.project_id == target.id))).scalars().all()
    assert len(nodes) == 2 and not {"n-conn", "n-csv"} & {node.ui_id for node in nodes}
    files = (await async_test_db_session.execute(sa.select(DVTServiceFileObjectRecord).where(DVTServiceFileObjectRecord.project_id == target.id))).scalars().all()
    assert len(files) == 1 and files[0].parent_path != "node-inputs/n-csv/file"
    await async_test_db_session.refresh(target)
    assert target.variables["limit"]["value"] == 10
    assert result.warnings == []


async def test_import_merge_rejects_multi_project_bundles_and_missing_target(async_test_db_session, org_and_users):
    _org, owner, _admin = org_and_users
    connections, node_types, schedules = _fakes()
    _source, bundle = await _exported_bundle(
        async_test_db_session, owner, connections=connections, node_types=node_types, schedules=schedules
    )
    use_case = _import_use_case(async_test_db_session, connections, node_types, schedules)

    with pytest.raises(ImportTargetNotFoundError):
        await use_case.execute(bundle, ImportTarget(mode=ImportMode.MERGE, project_id="missing"), ImportDecisions(), actor=_actor(owner))
    with pytest.raises(InvalidImportTargetError):
        await use_case.execute(bundle, ImportTarget(mode=ImportMode.MERGE), ImportDecisions(), actor=_actor(owner))
    bundle.projects.append(bundle.projects[0])
    with pytest.raises(InvalidImportTargetError):
        await use_case.execute(bundle, ImportTarget(mode=ImportMode.MERGE, project_id="x"), ImportDecisions(), actor=_actor(owner))


# --- preview and schedules ----------------------------------------------------


async def test_preview_reports_nodes_connections_variables_and_schedules(async_test_db_session, org_and_users):
    _org, owner, _admin = org_and_users
    connections, node_types, _schedules = _fakes()
    _source, bundle = await _exported_bundle(
        async_test_db_session,
        owner,
        connections=connections,
        node_types=node_types,
        schedules=FakeSchedules(snapshots={}),
        include_schedule=True,
    )
    bundle.projects[0].schedule = ScheduleSnapshot(cron="* * * * *", mode="full")
    target = await _seed_project(async_test_db_session, owner=owner, name="Target")
    async_test_db_session.add(ProjectScheduleRecord(project_id=target.id, cron="0 0 * * *"))
    await async_test_db_session.commit()
    target_node_types = FakeNodeTypes(
        connection_inputs={"GetExistDBConnection": ("connection_id",)},
        unknown={"LoadCSV"},
        extension_nodes={"GetExistDBConnection": ("ext.db", False)},
    )

    preview = await PreviewImportUseCase(
        repository=SQLProjectTransferWriteRepository(async_test_db_session),
        connections=connections,
        node_types=target_node_types,
    ).execute(bundle, ImportTarget(mode=ImportMode.MERGE, project_id=target.id), actor=_actor(owner))

    assert preview.unknown_node_names == ["LoadCSV"]
    assert preview.unavailable_extensions == ["ext.db"]
    assert preview.target_has_graph is True and preview.can_manage_schedules is False
    [project] = preview.projects
    assert (project.node_count, project.edge_count, project.subgraph_count) == (2, 1, 1)
    assert project.files_total_size == 5
    assert project.variables[0].key == "limit" and project.variables[0].conflicts_with_existing is True
    assert project.has_schedule_in_bundle is True and project.has_existing_schedule is True
    [connection] = preview.connections
    assert connection.candidates[0].id == "conn-src" and connection.has_secrets_in_bundle is False
    assert {w.code for w in preview.warnings} == {
        TransferWarningCode.UNKNOWN_NODE,
        TransferWarningCode.EXTENSION_UNAVAILABLE,
        TransferWarningCode.SCHEDULE_FORBIDDEN,
    }


async def test_import_schedule_decisions(async_test_db_session, org_and_users):
    _org, owner, admin = org_and_users
    connections, node_types, _ = _fakes()
    source_schedules = FakeSchedules()
    _source, bundle = await _exported_bundle(
        async_test_db_session, owner, connections=connections, node_types=node_types, schedules=source_schedules
    )
    bundle.projects[0].schedule = ScheduleSnapshot(cron="5 4 * * *", mode="full", max_retries=2)
    decisions = ImportDecisions(schedule=ScheduleDecision(import_schedule=True, enable=False))

    # Plain users get a warning, nothing is scheduled.
    schedules = FakeSchedules()
    result = await _import_use_case(async_test_db_session, connections, node_types, schedules).execute(
        bundle, ImportTarget(mode=ImportMode.CREATE), decisions, actor=_actor(owner)
    )
    assert TransferWarningCode.SCHEDULE_FORBIDDEN in {w.code for w in result.warnings}
    assert schedules.applied == []

    # Admins get the schedule applied, disabled when enable=False.
    result = await _import_use_case(async_test_db_session, connections, node_types, schedules).execute(
        bundle, ImportTarget(mode=ImportMode.CREATE), decisions, actor=_actor(admin, admin=True)
    )
    [(project_id, applied, enabled)] = schedules.applied
    assert project_id == result.project_ids["project-1"] and applied.cron == "5 4 * * *" and enabled is False

    # Merge keeps an existing schedule unless overwrite is requested.
    target = await _seed_project(async_test_db_session, owner=owner, name="Target")
    async_test_db_session.add(ProjectScheduleRecord(project_id=target.id, cron="0 0 * * *"))
    await async_test_db_session.commit()
    schedules = FakeSchedules()
    result = await _import_use_case(async_test_db_session, connections, node_types, schedules).execute(
        bundle, ImportTarget(mode=ImportMode.MERGE, project_id=target.id), decisions, actor=_actor(admin, admin=True)
    )
    assert TransferWarningCode.SCHEDULE_EXISTS in {w.code for w in result.warnings} and schedules.applied == []
    result = await _import_use_case(async_test_db_session, connections, node_types, schedules).execute(
        bundle,
        ImportTarget(mode=ImportMode.MERGE, project_id=target.id),
        ImportDecisions(schedule=ScheduleDecision(import_schedule=True, enable=True, conflict=ConflictDecision.OVERWRITE)),
        actor=_actor(admin, admin=True),
    )
    assert schedules.applied[0][2] is True

    # Scheduler outage does not undo the import.
    schedules = FakeSchedules(fail=True)
    result = await _import_use_case(async_test_db_session, connections, node_types, schedules).execute(
        bundle, ImportTarget(mode=ImportMode.CREATE), decisions, actor=_actor(admin, admin=True)
    )
    assert TransferWarningCode.SCHEDULE_IMPORT_FAILED in {w.code for w in result.warnings}
    assert await async_test_db_session.get(ProjectRecord, result.project_ids["project-1"]) is not None
