"""Orchestration shared by the preview and import use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.entities import ProjectBundle, TargetFolder, TargetProject
from ..domain.exceptions import (
    InvalidBundleError,
    InvalidConnectionDecisionError,
    InvalidImportTargetError,
)
from ..domain.gateways import ConnectionCatalogGateway, NodeTypeCatalog, SecretsCipher
from ..domain.policies import ensure_folder_depth_fits, order_folders
from ..domain.repositories import ProjectTransferWriteRepository
from ..domain.types import ConnectionDecisionAction, ImportMode, TransferWarningCode
from ..domain.value_objects import (
    ImportDecisions,
    ImportTarget,
    NodeTypeInfo,
    TransferActor,
    TransferWarning,
)
from .exceptions import ImportTargetNotFoundError


@dataclass
class ImportContext:
    """Validated target of an import."""

    target: ImportTarget
    folder: TargetFolder | None = None
    project: TargetProject | None = None


@dataclass
class NodeInspection:
    infos: dict[str, NodeTypeInfo] = field(default_factory=dict)

    @property
    def unknown_node_names(self) -> list[str]:
        return sorted(name for name, info in self.infos.items() if not info.known)

    @property
    def unavailable_extensions(self) -> list[str]:
        return sorted(
            {
                info.extension_name
                for info in self.infos.values()
                if info.known and info.extension_name and not info.extension_available
            }
        )

    def warnings(self) -> list[TransferWarning]:
        warnings = [
            TransferWarning(
                code=TransferWarningCode.UNKNOWN_NODE,
                message=f"Node '{name}' is not available on this instance",
                details={"node_name": name},
            )
            for name in self.unknown_node_names
        ]
        warnings.extend(
            TransferWarning(
                code=TransferWarningCode.EXTENSION_UNAVAILABLE,
                message=f"Extension '{extension}' is not installed, enabled and ready",
                details={"extension_name": extension},
            )
            for extension in self.unavailable_extensions
        )
        return warnings


@dataclass
class ConnectionResolution:
    connection_ids: dict[str, str] = field(default_factory=dict)
    skipped_refs: list[str] = field(default_factory=list)
    warnings: list[TransferWarning] = field(default_factory=list)


class ImportTargetValidator:
    def __init__(self, repository: ProjectTransferWriteRepository) -> None:
        self._repository = repository

    async def validate(
        self,
        bundle: ProjectBundle,
        target: ImportTarget,
        *,
        actor: TransferActor,
        lock_project: bool = False,
    ) -> ImportContext:
        if not bundle.projects and not bundle.folders:
            raise InvalidBundleError("Bundle contains no projects or folders")

        if target.mode == ImportMode.MERGE:
            if not target.project_id:
                raise InvalidImportTargetError("Merge import requires a target project")
            if len(bundle.projects) != 1:
                raise InvalidImportTargetError(
                    "Merge import requires a bundle with exactly one project, "
                    f"got {len(bundle.projects)}"
                )
            project = await self._repository.get_target_project(
                target.project_id,
                actor=actor,
                lock=lock_project,
            )
            if project is None:
                raise ImportTargetNotFoundError(f"Project '{target.project_id}' was not found")
            return ImportContext(target=target, project=project)

        folder = None
        target_depth = 0
        if target.folder_id:
            folder = await self._repository.get_target_folder(target.folder_id, actor=actor)
            if folder is None:
                raise ImportTargetNotFoundError(f"Folder '{target.folder_id}' was not found")
            target_depth = folder.depth
        order_folders(bundle.folders)
        ensure_folder_depth_fits(bundle.folders, target_depth=target_depth)
        return ImportContext(target=target, folder=folder)


class NodeInspector:
    def __init__(self, catalog: NodeTypeCatalog) -> None:
        self._catalog = catalog

    async def inspect(self, bundle: ProjectBundle) -> NodeInspection:
        inspection = NodeInspection()
        for project in bundle.projects:
            for node in project.graph.nodes:
                if node.name not in inspection.infos:
                    inspection.infos[node.name] = await self._catalog.describe(node.name)
        return inspection


class BundleSecretsOpener:
    def __init__(self, cipher: SecretsCipher) -> None:
        self._cipher = cipher

    def open(self, bundle: ProjectBundle, *, passphrase: str | None) -> dict[str, dict[str, Any]]:
        if bundle.secrets is not None:
            return bundle.secrets
        if not bundle.encrypted_secrets or not passphrase:
            return {}
        secrets = self._cipher.decrypt(bundle.encrypted_secrets, passphrase=passphrase)
        return {ref: value for ref, value in secrets.items() if isinstance(value, dict)}


class ConnectionResolver:
    """Turns per-connection decisions into concrete connection ids on this instance."""

    def __init__(self, gateway: ConnectionCatalogGateway) -> None:
        self._gateway = gateway

    async def resolve(
        self,
        bundle: ProjectBundle,
        decisions: ImportDecisions,
        *,
        bundle_secrets: dict[str, dict[str, Any]],
        actor: TransferActor,
    ) -> ConnectionResolution:
        resolution = ConnectionResolution()
        used_refs = sorted({ref for project in bundle.projects for ref in project.connection_refs})

        for ref in used_refs:
            decision = decisions.connections.get(ref)
            connection = bundle.connection_by_ref(ref)
            label = connection.name if connection and connection.name else ref

            if decision is None or decision.action == ConnectionDecisionAction.SKIP:
                resolution.skipped_refs.append(ref)
                resolution.warnings.append(
                    TransferWarning(
                        code=TransferWarningCode.CONNECTION_SKIPPED,
                        message=f"Connection '{label}' was not mapped; nodes using it will fail until fixed",
                        details={"connection_ref": ref},
                    )
                )
                continue

            if decision.action == ConnectionDecisionAction.USE_EXISTING:
                if not decision.connection_id:
                    raise InvalidConnectionDecisionError(f"Connection '{ref}': use_existing requires connection_id")
                if not await self._gateway.exists(decision.connection_id, actor=actor):
                    raise InvalidConnectionDecisionError(
                        f"Connection '{ref}': connection '{decision.connection_id}' is not accessible"
                    )
                resolution.connection_ids[ref] = decision.connection_id
                continue

            if connection is None or connection.inaccessible:
                raise InvalidConnectionDecisionError(
                    f"Connection '{ref}' cannot be created: the bundle has no definition for it"
                )
            secrets = decision.secrets if decision.secrets is not None else bundle_secrets.get(ref, {})
            try:
                resolution.connection_ids[ref] = await self._gateway.create(
                    connection,
                    secrets=secrets,
                    actor=actor,
                )
            except Exception as exc:
                resolution.skipped_refs.append(ref)
                resolution.warnings.append(
                    TransferWarning(
                        code=TransferWarningCode.CONNECTION_CREATE_FAILED,
                        message=f"Connection '{label}' could not be created: {exc}",
                        details={"connection_ref": ref},
                    )
                )
        return resolution
