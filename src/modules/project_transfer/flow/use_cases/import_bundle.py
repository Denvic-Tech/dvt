from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ...domain.entities import BundleProject, ImportResult, ProjectBundle, TargetProject
from ...domain.gateways import (
    ConnectionCatalogGateway,
    NodeTypeCatalog,
    ScheduleGateway,
    SecretsCipher,
)
from ...domain.policies import (
    apply_connection_ids,
    order_folders,
    rebase_project_files,
    remap_graph_snapshot,
    resolve_variables,
)
from ...domain.repositories import ProjectTransferWriteRepository
from ...domain.types import ConflictDecision, ImportMode, MergeStrategy, TransferWarningCode
from ...domain.value_objects import ImportDecisions, ImportTarget, TransferActor, TransferWarning
from ..providers import (
    BundleSecretsOpener,
    ConnectionResolver,
    ImportContext,
    ImportTargetValidator,
    NodeInspector,
)


class ImportBundleUseCase:
    def __init__(
        self,
        *,
        repository: ProjectTransferWriteRepository,
        connections: ConnectionCatalogGateway,
        node_types: NodeTypeCatalog,
        schedules: ScheduleGateway,
        cipher: SecretsCipher,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._repository = repository
        self._validator = ImportTargetValidator(repository)
        self._nodes = NodeInspector(node_types)
        self._secrets = BundleSecretsOpener(cipher)
        self._connections = ConnectionResolver(connections)
        self._schedules = schedules
        self._clock = clock

    async def execute(
        self,
        bundle: ProjectBundle,
        target: ImportTarget,
        decisions: ImportDecisions,
        *,
        actor: TransferActor,
    ) -> ImportResult:
        context = await self._validator.validate(bundle, target, actor=actor, lock_project=True)
        result = ImportResult()
        result.warnings.extend((await self._nodes.inspect(bundle)).warnings())

        bundle_secrets = self._secrets.open(bundle, passphrase=decisions.passphrase)
        resolution = await self._connections.resolve(
            bundle,
            decisions,
            bundle_secrets=bundle_secrets,
            actor=actor,
        )
        result.connection_ids = resolution.connection_ids
        result.skipped_connection_refs = resolution.skipped_refs
        result.warnings.extend(resolution.warnings)

        now = self._clock()
        try:
            if context.target.mode == ImportMode.MERGE:
                await self._merge(bundle.projects[0], context, decisions, result, now=now)
            else:
                await self._create(bundle, context, decisions, result, actor=actor, now=now)
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise

        organization_id = (
            context.project.organization_id if context.project is not None else actor.organization_id
        )
        for project_ref, project_id in result.project_ids.items():
            try:
                await self._repository.rebuild_catalog(project_id, organization_id=organization_id)
            except Exception as exc:
                result.warnings.append(
                    TransferWarning(
                        code=TransferWarningCode.CATALOG_REBUILD_FAILED,
                        message=f"Data catalog projection could not be rebuilt: {exc}",
                        project_ref=project_ref,
                        details={"project_id": project_id},
                    )
                )

        await self._apply_schedules(bundle, context, decisions, result, actor=actor)
        return result

    async def _create(
        self,
        bundle: ProjectBundle,
        context: ImportContext,
        decisions: ImportDecisions,
        result: ImportResult,
        *,
        actor: TransferActor,
        now: datetime,
    ) -> None:
        for folder, _depth in order_folders(bundle.folders):
            parent_id = result.folder_ids[folder.parent_ref] if folder.parent_ref else context.target.folder_id
            result.folder_ids[folder.ref] = await self._repository.create_folder(
                name=folder.name,
                parent_id=parent_id,
                actor=actor,
                now=now,
            )

        for project in bundle.projects:
            folder_id = result.folder_ids.get(project.folder_ref) if project.folder_ref else context.target.folder_id
            variables, _kept = resolve_variables(None, project.variables, decisions.variables.get(project.ref))
            project_id = await self._repository.create_project(
                meta=project.meta,
                folder_id=folder_id,
                variables=variables or None,
                actor=actor,
                now=now,
            )
            result.project_ids[project.ref] = project_id
            await self._write_graph(
                project,
                project_id=project_id,
                owner_user_id=actor.user_id,
                organization_id=actor.organization_id,
                connection_ids=result.connection_ids,
                now=now,
            )

    async def _merge(
        self,
        project: BundleProject,
        context: ImportContext,
        decisions: ImportDecisions,
        result: ImportResult,
        *,
        now: datetime,
    ) -> None:
        target: TargetProject = context.project  # validated by ImportTargetValidator
        result.project_ids[project.ref] = target.id

        removed_node_ui_ids: list[str] = []
        if context.target.merge_strategy == MergeStrategy.REPLACE:
            removed_node_ui_ids = await self._repository.clear_graph(target.id)

        new_node_ui_ids = await self._write_graph(
            project,
            project_id=target.id,
            owner_user_id=target.user_id,
            organization_id=target.organization_id,
            connection_ids=result.connection_ids,
            now=now,
        )

        project_decisions = decisions.variables.get(project.ref)
        if project.variables or project_decisions:
            merged, kept = resolve_variables(target.variables, project.variables, project_decisions)
            await self._repository.set_variables(target.id, merged or None)
            for key in kept:
                result.warnings.append(
                    TransferWarning(
                        code=TransferWarningCode.VARIABLE_CONFLICT,
                        message=f"Variable '{key}' already exists and was kept",
                        project_ref=project.ref,
                        details={"key": key},
                    )
                )

        await self._repository.mark_graph_changed(
            target.id,
            organization_id=target.organization_id,
            node_ui_ids=new_node_ui_ids,
            removed_node_ui_ids=removed_node_ui_ids,
        )

    async def _write_graph(
        self,
        project: BundleProject,
        *,
        project_id: str,
        owner_user_id: str,
        organization_id: str,
        connection_ids: dict[str, str],
        now: datetime,
    ) -> list[str]:
        remapped = remap_graph_snapshot(project.graph, organization_id=organization_id, project_id=project_id)
        snapshot = apply_connection_ids(
            remapped.snapshot,
            project.connection_bindings,
            connection_ids,
            node_ui_id_mapping=remapped.mapping.nodes,
        )
        await self._repository.insert_graph(
            project_id,
            snapshot,
            owner_user_id=owner_user_id,
            organization_id=organization_id,
            now=now,
        )
        await self._repository.insert_files(
            project_id,
            rebase_project_files(project.files, remapped.service_files_rewrites),
            organization_id=organization_id,
            now=now,
        )
        return [node.ui_id for node in snapshot.nodes]

    async def _apply_schedules(
        self,
        bundle: ProjectBundle,
        context: ImportContext,
        decisions: ImportDecisions,
        result: ImportResult,
        *,
        actor: TransferActor,
    ) -> None:
        if not decisions.schedule.import_schedule:
            return
        scheduled = [project for project in bundle.projects if project.schedule is not None]
        if not scheduled:
            return
        if not actor.can_manage_schedules:
            result.warnings.append(
                TransferWarning(
                    code=TransferWarningCode.SCHEDULE_FORBIDDEN,
                    message="Only administrators may import schedules; schedules were skipped",
                )
            )
            return

        for project in scheduled:
            project_id = result.project_ids[project.ref]
            if (
                context.target.mode == ImportMode.MERGE
                and context.project is not None
                and context.project.has_schedule
                and decisions.schedule.conflict != ConflictDecision.OVERWRITE
            ):
                result.warnings.append(
                    TransferWarning(
                        code=TransferWarningCode.SCHEDULE_EXISTS,
                        message="Target project already has a schedule; it was kept",
                        project_ref=project.ref,
                        details={"project_id": project_id},
                    )
                )
                continue
            try:
                await self._schedules.apply(
                    project_id,
                    project.schedule,
                    enabled=decisions.schedule.enable,
                    actor=actor,
                    replace_existing=True,
                )
            except Exception as exc:
                result.warnings.append(
                    TransferWarning(
                        code=TransferWarningCode.SCHEDULE_IMPORT_FAILED,
                        message=f"Schedule could not be applied: {exc}",
                        project_ref=project.ref,
                        details={"project_id": project_id},
                    )
                )
