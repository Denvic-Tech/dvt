"""Bundle documents / HTTP payloads <-> domain objects."""

from __future__ import annotations

from dataclasses import asdict

from src.modules.project_transfer.domain import entities as d
from src.modules.project_transfer.domain.value_objects import (
    ConnectionBinding,
    ConnectionDecision,
    ExistingConnection,
    ExportOptions,
    ExportSelection,
    ImportDecisions,
    ImportTarget,
    ScheduleDecision,
    TransferWarning,
    VariableDecision,
)
from src.utils.project_variables import normalize_project_variable_storage_payload

from . import schemas as s

# --- Bundle documents --------------------------------------------------------


def manifest_to_doc(bundle: d.ProjectBundle) -> s.BundleManifestDoc:
    manifest = bundle.manifest
    return s.BundleManifestDoc(
        format_version=manifest.format_version,
        dvt_version=manifest.dvt_version,
        exported_at=manifest.exported_at,
        source_instance_id=manifest.source_instance_id,
        options=dict(manifest.options),
        required_node_types=[s.RequiredNodeTypeDoc(**asdict(item)) for item in manifest.required_node_types],
        has_secrets=manifest.has_secrets,
        folders=[s.BundleFolderDoc(**asdict(folder)) for folder in bundle.folders],
        projects=[
            s.ManifestProjectEntryDoc(ref=project.ref, name=project.meta.name, folder_ref=project.folder_ref)
            for project in bundle.projects
        ],
    )


def manifest_from_doc(doc: s.BundleManifestDoc) -> d.BundleManifest:
    return d.BundleManifest(
        format_version=doc.format_version,
        dvt_version=doc.dvt_version,
        exported_at=doc.exported_at,
        source_instance_id=doc.source_instance_id,
        options=dict(doc.options),
        required_node_types=[d.RequiredNodeType(**item.model_dump()) for item in doc.required_node_types],
        has_secrets=doc.has_secrets,
    )


def folder_from_doc(doc: s.BundleFolderDoc) -> d.BundleFolder:
    return d.BundleFolder(**doc.model_dump())


def connection_to_doc(connection: d.BundleConnection) -> s.BundleConnectionDoc:
    return s.BundleConnectionDoc(**asdict(connection))


def connection_from_doc(doc: s.BundleConnectionDoc) -> d.BundleConnection:
    return d.BundleConnection(**doc.model_dump())


def graph_to_doc(graph: d.GraphSnapshot) -> s.GraphDoc:
    return s.GraphDoc(
        subgraphs=[s.GraphSubgraphDoc(**asdict(item)) for item in graph.subgraphs],
        nodes=[s.GraphNodeDoc(**asdict(item)) for item in graph.nodes],
        edges=[s.GraphEdgeDoc(**asdict(item)) for item in graph.edges],
        column_annotations=[s.ColumnAnnotationDoc(**asdict(item)) for item in graph.column_annotations],
    )


def graph_from_doc(doc: s.GraphDoc) -> d.GraphSnapshot:
    return d.GraphSnapshot(
        subgraphs=[d.GraphSubgraphSnapshot(**item.model_dump()) for item in doc.subgraphs],
        nodes=[d.GraphNodeSnapshot(**item.model_dump()) for item in doc.nodes],
        edges=[d.GraphEdgeSnapshot(**item.model_dump()) for item in doc.edges],
        column_annotations=[
            d.ColumnAnnotationSnapshot(**item.model_dump()) for item in doc.column_annotations
        ],
    )


def project_to_doc(project: d.BundleProject) -> s.BundleProjectDoc:
    return s.BundleProjectDoc(
        ref=project.ref,
        folder_ref=project.folder_ref,
        meta=s.ProjectMetaDoc(**asdict(project.meta)),
        variables=project.variables,
        graph=graph_to_doc(project.graph),
        files=[
            s.ProjectFileDoc(
                storage_path=file.storage_path,
                is_dir=file.is_dir,
                size=file.size,
                sha256=file.sha256,
                content_type=file.content_type,
            )
            for file in project.files
        ],
        schedule=s.ScheduleDoc(**asdict(project.schedule)) if project.schedule else None,
        connection_bindings=[s.ConnectionBindingDoc(**asdict(b)) for b in project.connection_bindings],
    )


def project_from_doc(doc: s.BundleProjectDoc) -> d.BundleProject:
    return d.BundleProject(
        ref=doc.ref,
        folder_ref=doc.folder_ref,
        meta=d.ProjectMeta(**doc.meta.model_dump()),
        variables=doc.variables,
        graph=graph_from_doc(doc.graph),
        files=[d.ProjectFile(**file.model_dump()) for file in doc.files],
        schedule=d.ScheduleSnapshot(**doc.schedule.model_dump()) if doc.schedule else None,
        connection_bindings=[ConnectionBinding(**b.model_dump()) for b in doc.connection_bindings],
    )


# --- HTTP requests -----------------------------------------------------------


def export_request_to_domain(request: s.ExportRequestSchema) -> tuple[ExportSelection, ExportOptions]:
    selection = ExportSelection(
        project_ids=tuple(dict.fromkeys(request.project_ids)),
        folder_ids=tuple(dict.fromkeys(request.folder_ids)),
    )
    options = ExportOptions(
        include_variables=request.include_variables,
        include_connections=request.include_connections,
        include_secrets=request.include_secrets,
        include_files=request.include_files,
        include_schedule=request.include_schedule,
        disable_schedule_after_export=request.disable_schedule_after_export,
        passphrase=request.passphrase,
    )
    return selection, options


def import_request_to_domain(request: s.ImportRequestSchema) -> tuple[ImportTarget, ImportDecisions]:
    target = ImportTarget(
        mode=request.mode,
        folder_id=request.folder_id,
        project_id=request.project_id,
        merge_strategy=request.merge_strategy,
    )
    decisions = ImportDecisions(
        connections={
            ref: ConnectionDecision(
                action=decision.action,
                connection_id=decision.connection_id,
                secrets=decision.secrets,
            )
            for ref, decision in request.connections.items()
        },
        variables={
            project_ref: {
                key: VariableDecision(
                    value=(
                        normalize_project_variable_storage_payload(decision.value.model_dump(), allow_legacy=False)
                        if decision.value is not None
                        else None
                    ),
                    conflict=decision.conflict,
                )
                for key, decision in per_project.items()
            }
            for project_ref, per_project in request.variables.items()
        },
        schedule=ScheduleDecision(
            import_schedule=request.schedule.import_schedule,
            enable=request.schedule.enable,
            conflict=request.schedule.conflict,
        ),
        passphrase=request.passphrase,
    )
    return target, decisions


# --- HTTP responses ----------------------------------------------------------


def warning_to_schema(warning: TransferWarning) -> s.TransferWarningSchema:
    return s.TransferWarningSchema(
        code=warning.code,
        message=warning.message,
        project_ref=warning.project_ref,
        details=dict(warning.details),
    )


def _existing_connection_to_schema(connection: ExistingConnection) -> s.ExistingConnectionSchema:
    return s.ExistingConnectionSchema(**asdict(connection))


def preview_to_schema(preview: d.ImportPreview) -> s.ImportPreviewSchema:
    manifest = preview.manifest
    return s.ImportPreviewSchema(
        manifest=s.ManifestInfoSchema(
            format_version=manifest.format_version,
            dvt_version=manifest.dvt_version,
            exported_at=manifest.exported_at,
            source_instance_id=manifest.source_instance_id,
            options=dict(manifest.options),
            has_secrets=manifest.has_secrets,
        ),
        folders=[s.BundleFolderDoc(**asdict(folder)) for folder in preview.folders],
        projects=[
            s.ProjectPreviewSchema(
                ref=project.ref,
                name=project.name,
                folder_ref=project.folder_ref,
                node_count=project.node_count,
                edge_count=project.edge_count,
                subgraph_count=project.subgraph_count,
                files_total_size=project.files_total_size,
                variables=[
                    s.VariablePreviewSchema(
                        key=variable.key,
                        value=variable.value,
                        conflicts_with_existing=variable.conflicts_with_existing,
                    )
                    for variable in project.variables
                ],
                has_schedule_in_bundle=project.has_schedule_in_bundle,
                has_existing_schedule=project.has_existing_schedule,
            )
            for project in preview.projects
        ],
        connections=[
            s.ConnectionPreviewSchema(
                ref=connection.ref,
                name=connection.name,
                kind=connection.kind,
                type=connection.type,
                inaccessible=connection.inaccessible,
                has_secrets_in_bundle=connection.has_secrets_in_bundle,
                candidates=[_existing_connection_to_schema(c) for c in connection.candidates],
            )
            for connection in preview.connections
        ],
        unknown_node_names=list(preview.unknown_node_names),
        unavailable_extensions=list(preview.unavailable_extensions),
        target_has_graph=preview.target_has_graph,
        can_manage_schedules=preview.can_manage_schedules,
        warnings=[warning_to_schema(w) for w in preview.warnings],
    )


def result_to_schema(result: d.ImportResult) -> s.ImportResultSchema:
    return s.ImportResultSchema(
        folder_ids=dict(result.folder_ids),
        project_ids=dict(result.project_ids),
        connection_ids=dict(result.connection_ids),
        skipped_connection_refs=list(result.skipped_connection_refs),
        warnings=[warning_to_schema(w) for w in result.warnings],
    )
