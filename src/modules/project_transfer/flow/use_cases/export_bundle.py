from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime

from ...domain.entities import (
    BundleConnection,
    BundleFolder,
    BundleManifest,
    BundleProject,
    ExportResult,
    ProjectBundle,
    RequiredNodeType,
    SourceProject,
)
from ...domain.exceptions import EmptyExportSelectionError
from ...domain.gateways import (
    ConnectionCatalogGateway,
    InstanceInfoProvider,
    NodeTypeCatalog,
    ScheduleGateway,
    SecretsCipher,
)
from ...domain.policies import collect_connection_inputs, validate_passphrase
from ...domain.repositories import ProjectTransferReadRepository
from ...domain.types import BUNDLE_FILE_EXTENSION, BUNDLE_FORMAT_VERSION, TransferWarningCode
from ...domain.value_objects import (
    ConnectionBinding,
    ExportOptions,
    ExportSelection,
    TransferActor,
    TransferWarning,
)
from ..exceptions import ExportSelectionNotFoundError

_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w\-. ]+", re.UNICODE)


def _safe_file_stem(name: str, fallback: str) -> str:
    stem = _UNSAFE_FILENAME_CHARS.sub("_", name).strip(" ._")
    return stem[:80] or fallback


class ExportBundleUseCase:
    def __init__(
        self,
        *,
        repository: ProjectTransferReadRepository,
        connections: ConnectionCatalogGateway,
        node_types: NodeTypeCatalog,
        schedules: ScheduleGateway,
        cipher: SecretsCipher,
        instance_info: InstanceInfoProvider,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._repository = repository
        self._connections = connections
        self._node_types = node_types
        self._schedules = schedules
        self._cipher = cipher
        self._instance_info = instance_info
        self._clock = clock

    async def execute(
        self,
        selection: ExportSelection,
        options: ExportOptions,
        *,
        actor: TransferActor,
    ) -> ExportResult:
        if selection.is_empty:
            raise EmptyExportSelectionError()
        passphrase = validate_passphrase(options.passphrase) if options.include_secrets else None

        folders, folder_projects = await self._repository.get_folder_subtrees(selection.folder_ids, actor=actor)
        direct_projects = await self._repository.get_projects(selection.project_ids, actor=actor)
        projects: dict[str, SourceProject] = {project.id: project for project in folder_projects}
        for project in direct_projects:
            projects.setdefault(project.id, project)
        if not projects and not folders:
            raise ExportSelectionNotFoundError()

        folder_refs = {folder.id: f"folder-{index + 1}" for index, folder in enumerate(folders)}
        bundle_folders = [
            BundleFolder(
                ref=folder_refs[folder.id],
                name=folder.name,
                parent_ref=folder_refs.get(folder.parent_id) if folder.parent_id else None,
            )
            for folder in folders
        ]

        warnings: list[TransferWarning] = []
        required_nodes: dict[str, RequiredNodeType] = {}
        connection_refs: dict[str, str] = {}
        bundle_connections: list[BundleConnection] = []
        secrets: dict[str, dict] = {}
        bundle_projects: list[BundleProject] = []
        ordered_projects = sorted(projects.values(), key=lambda item: (item.meta.name or "", item.id))

        for index, source in enumerate(ordered_projects):
            project_ref = f"project-{index + 1}"
            graph = await self._repository.read_graph(source.id)

            connection_inputs_by_node: dict[str, tuple[str, ...] | None] = {}
            for node in graph.nodes:
                if node.name in connection_inputs_by_node:
                    continue
                info = await self._node_types.describe(node.name)
                connection_inputs_by_node[node.name] = info.connection_input_names if info.known else None
                if info.known:
                    required_nodes.setdefault(
                        node.name,
                        RequiredNodeType(
                            name=node.name,
                            extension_name=info.extension_name,
                            extension_version=info.extension_version,
                        ),
                    )
                else:
                    required_nodes.setdefault(node.name, RequiredNodeType(name=node.name))
                    warnings.append(
                        TransferWarning(
                            code=TransferWarningCode.UNKNOWN_NODE,
                            message=f"Node '{node.name}' is unknown on this instance; its inputs were exported as-is",
                            project_ref=project_ref,
                            details={"node_name": node.name},
                        )
                    )

            bindings: list[ConnectionBinding] = []
            if options.include_connections:
                for node_ui_id, input_name, connection_id in collect_connection_inputs(
                    graph, connection_inputs_by_node
                ):
                    ref = connection_refs.get(connection_id)
                    if ref is None:
                        ref = f"connection-{len(connection_refs) + 1}"
                        connection_refs[connection_id] = ref
                        described = await self._connections.describe(connection_id, actor=actor, ref=ref)
                        if described is None:
                            described = BundleConnection(
                                ref=ref,
                                name="",
                                kind="unknown",
                                type="unknown",
                                inaccessible=True,
                            )
                            warnings.append(
                                TransferWarning(
                                    code=TransferWarningCode.CONNECTION_INACCESSIBLE,
                                    message=f"Connection '{connection_id}' is not accessible and was exported as a stub",
                                    project_ref=project_ref,
                                    details={"connection_ref": ref},
                                )
                            )
                        elif options.include_secrets:
                            connection_secrets = await self._connections.read_secrets(connection_id, actor=actor)
                            if connection_secrets is None:
                                warnings.append(
                                    TransferWarning(
                                        code=TransferWarningCode.SECRETS_UNAVAILABLE,
                                        message=f"Secrets of connection '{described.name}' could not be read",
                                        project_ref=project_ref,
                                        details={"connection_ref": ref},
                                    )
                                )
                            else:
                                secrets[ref] = connection_secrets
                        bundle_connections.append(described)
                    bindings.append(
                        ConnectionBinding(node_ui_id=node_ui_id, input_name=input_name, connection_ref=ref)
                    )

            bundle_projects.append(
                BundleProject(
                    ref=project_ref,
                    folder_ref=folder_refs.get(source.folder_id) if source.folder_id else None,
                    meta=source.meta,
                    graph=graph,
                    variables=dict(source.variables) if options.include_variables and source.variables else None,
                    files=(
                        await self._repository.read_files(source.id, with_content=True)
                        if options.include_files
                        else []
                    ),
                    schedule=await self._schedules.read(source.id) if options.include_schedule else None,
                    connection_bindings=bindings,
                )
            )

        instance = self._instance_info.get()
        bundle = ProjectBundle(
            manifest=BundleManifest(
                format_version=BUNDLE_FORMAT_VERSION,
                dvt_version=instance.version,
                exported_at=self._clock(),
                source_instance_id=instance.instance_id,
                options=options.public_dict(),
                required_node_types=sorted(required_nodes.values(), key=lambda item: item.name),
                has_secrets=bool(secrets),
            ),
            folders=bundle_folders,
            projects=bundle_projects,
            connections=bundle_connections,
            secrets=secrets or None,
            encrypted_secrets=self._cipher.encrypt(secrets, passphrase=passphrase) if secrets and passphrase else None,
        )

        root_folders = [folder for folder in folders if folder.parent_id is None]
        if len(ordered_projects) == 1 and not folders:
            stem = _safe_file_stem(ordered_projects[0].meta.name or "", "project")
        elif len(root_folders) == 1 and len(selection.folder_ids) == 1 and not selection.project_ids:
            stem = _safe_file_stem(root_folders[0].name, "folder")
        else:
            stem = f"dvt-export-{self._clock():%Y%m%d-%H%M%S}"

        return ExportResult(
            bundle=bundle,
            warnings=warnings,
            file_name=f"{stem}{BUNDLE_FILE_EXTENSION}",
            schedule_project_ids=[
                project_id
                for project_id, project in zip((p.id for p in ordered_projects), bundle_projects, strict=True)
                if project.schedule is not None and not project.schedule.disabled
            ],
        )
