from __future__ import annotations

from ...domain.entities import (
    ConnectionPreview,
    ImportPreview,
    ProjectBundle,
    ProjectPreview,
    VariablePreview,
)
from ...domain.gateways import ConnectionCatalogGateway, NodeTypeCatalog
from ...domain.repositories import ProjectTransferWriteRepository
from ...domain.types import ImportMode, TransferWarningCode
from ...domain.value_objects import ImportTarget, TransferActor, TransferWarning
from ..providers import ImportTargetValidator, NodeInspector


class PreviewImportUseCase:
    def __init__(
        self,
        *,
        repository: ProjectTransferWriteRepository,
        connections: ConnectionCatalogGateway,
        node_types: NodeTypeCatalog,
    ) -> None:
        self._validator = ImportTargetValidator(repository)
        self._connections = connections
        self._nodes = NodeInspector(node_types)

    async def execute(
        self,
        bundle: ProjectBundle,
        target: ImportTarget,
        *,
        actor: TransferActor,
    ) -> ImportPreview:
        context = await self._validator.validate(bundle, target, actor=actor)
        inspection = await self._nodes.inspect(bundle)
        warnings: list[TransferWarning] = inspection.warnings()

        existing_variables = (
            context.project.variables or {}
            if context.target.mode == ImportMode.MERGE and context.project is not None
            else {}
        )
        projects = []
        for project in bundle.projects:
            projects.append(
                ProjectPreview(
                    ref=project.ref,
                    name=project.meta.name,
                    folder_ref=project.folder_ref,
                    node_count=len(project.graph.nodes),
                    edge_count=len(project.graph.edges),
                    subgraph_count=len(project.graph.subgraphs),
                    files_total_size=sum(file.size for file in project.files if not file.is_dir),
                    variables=[
                        VariablePreview(
                            key=key,
                            value=value,
                            conflicts_with_existing=key in existing_variables,
                        )
                        for key, value in (project.variables or {}).items()
                    ],
                    has_schedule_in_bundle=project.schedule is not None,
                    has_existing_schedule=bool(context.project and context.project.has_schedule),
                )
            )

        used_refs = {ref for project in bundle.projects for ref in project.connection_refs}
        connections = []
        for connection in bundle.connections:
            if connection.ref not in used_refs:
                continue
            if connection.inaccessible:
                warnings.append(
                    TransferWarning(
                        code=TransferWarningCode.CONNECTION_INACCESSIBLE,
                        message=f"Connection '{connection.ref}' was exported without a definition; map it to an existing one",
                        details={"connection_ref": connection.ref},
                    )
                )
            connections.append(
                ConnectionPreview(
                    ref=connection.ref,
                    name=connection.name,
                    kind=connection.kind,
                    type=connection.type,
                    inaccessible=connection.inaccessible,
                    has_secrets_in_bundle=bundle.manifest.has_secrets and not connection.inaccessible,
                    candidates=(
                        []
                        if connection.inaccessible
                        else await self._connections.find_candidates(connection, actor=actor)
                    ),
                )
            )

        if any(project.schedule is not None for project in bundle.projects) and not actor.can_manage_schedules:
            warnings.append(
                TransferWarning(
                    code=TransferWarningCode.SCHEDULE_FORBIDDEN,
                    message="Bundle contains schedules, but only administrators may import them",
                )
            )

        return ImportPreview(
            manifest=bundle.manifest,
            folders=list(bundle.folders),
            projects=projects,
            connections=connections,
            unknown_node_names=inspection.unknown_node_names,
            unavailable_extensions=inspection.unavailable_extensions,
            target_has_graph=bool(context.project and context.project.has_graph),
            can_manage_schedules=actor.can_manage_schedules,
            warnings=warnings,
        )
