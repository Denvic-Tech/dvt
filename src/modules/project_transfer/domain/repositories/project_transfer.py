from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from ..entities import (
    GraphSnapshot,
    ProjectFile,
    ProjectMeta,
    SourceFolder,
    SourceProject,
    TargetFolder,
    TargetProject,
)
from ..value_objects import TransferActor


class ProjectTransferReadRepository(Protocol):
    """Read side of a transfer: what the actor may export."""

    async def get_projects(
        self,
        project_ids: Sequence[str],
        *,
        actor: TransferActor,
    ) -> list[SourceProject]:
        """Accessible, non-deleted projects among ``project_ids``."""
        ...

    async def get_folder_subtrees(
        self,
        folder_ids: Sequence[str],
        *,
        actor: TransferActor,
    ) -> tuple[list[SourceFolder], list[SourceProject]]:
        """Accessible folders (roots included) with every descendant folder and project."""
        ...

    async def read_graph(self, project_id: str) -> GraphSnapshot: ...

    async def read_files(self, project_id: str, *, with_content: bool) -> list[ProjectFile]: ...


class ProjectTransferWriteRepository(Protocol):
    """Write side of a transfer. Calls share one transaction until ``commit``."""

    async def get_target_folder(
        self,
        folder_id: str,
        *,
        actor: TransferActor,
    ) -> TargetFolder | None: ...

    async def get_target_project(
        self,
        project_id: str,
        *,
        actor: TransferActor,
        lock: bool = False,
    ) -> TargetProject | None: ...

    async def create_folder(
        self,
        *,
        name: str,
        parent_id: str | None,
        actor: TransferActor,
        now: datetime,
    ) -> str: ...

    async def create_project(
        self,
        *,
        meta: ProjectMeta,
        folder_id: str | None,
        variables: dict[str, dict[str, Any]] | None,
        actor: TransferActor,
        now: datetime,
    ) -> str: ...

    async def set_variables(
        self,
        project_id: str,
        variables: dict[str, dict[str, Any]] | None,
    ) -> None: ...

    async def clear_graph(self, project_id: str) -> list[str]:
        """Delete the graph and node files of a project; returns removed node ui_ids."""
        ...

    async def insert_graph(
        self,
        project_id: str,
        snapshot: GraphSnapshot,
        *,
        owner_user_id: str,
        organization_id: str,
        now: datetime,
    ) -> None: ...

    async def insert_files(
        self,
        project_id: str,
        files: Sequence[ProjectFile],
        *,
        organization_id: str,
        now: datetime,
    ) -> None: ...

    async def mark_graph_changed(
        self,
        project_id: str,
        *,
        organization_id: str,
        node_ui_ids: Sequence[str],
        removed_node_ui_ids: Sequence[str] = (),
    ) -> None:
        """Record changed nodes and bump the graph revision after a merge."""
        ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def rebuild_catalog(self, project_id: str, *, organization_id: str) -> None:
        """Post-commit catalog projection refresh; raises on failure."""
        ...
