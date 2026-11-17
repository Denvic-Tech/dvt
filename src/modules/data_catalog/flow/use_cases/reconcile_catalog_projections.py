"""Сверка проекций каталога: обход проектов keyset-страницами и пересборка каждого отдельно.

Use case не владеет транзакциями: пересборку одного проекта выполняет внедрённый runner,
который открывает собственную сессию, коммитит или откатывает её и возвращает RebuildResult.
Исключение runner'а засчитывается как failed и не останавливает обход.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from src.logger import logger

from ...domain import (
    LINEAGE_SCHEMA_VERSION,
    CatalogProjectSource,
    ProjectRef,
    RebuildResult,
    ReconcileSummary,
)

ProjectRebuildRunner = Callable[[ProjectRef, bool], Awaitable[RebuildResult]]
YieldControl = Callable[[], Awaitable[None]]

_MAX_ERROR_LENGTH = 200


async def _yield_to_event_loop() -> None:
    await asyncio.sleep(0)


class ReconcileCatalogProjections:
    def __init__(
        self,
        *,
        projects: CatalogProjectSource,
        rebuild_one: ProjectRebuildRunner,
        batch_size: int = 100,
        yield_control: YieldControl | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._projects = projects
        self._rebuild_one = rebuild_one
        self._batch_size = batch_size
        self._yield = yield_control or _yield_to_event_loop

    async def execute(
        self,
        *,
        force: bool = False,
        dry_run: bool = False,
        organization_id: str | None = None,
        project_ids: Sequence[str] | None = None,
    ) -> ReconcileSummary:
        """force=True пересобирает все выбранные проекты, иначе только устаревшие."""
        summary = ReconcileSummary()
        after: str | None = None
        while True:
            page = await self._projects.list_projects(
                lineage_schema_version=LINEAGE_SCHEMA_VERSION,
                stale_only=not force,
                after_project_id=after,
                limit=self._batch_size,
                organization_id=organization_id,
                project_ids=project_ids,
            )
            if not page:
                break
            for project in page:
                summary.total += 1
                if dry_run:
                    summary.skipped += 1
                    continue
                await self._reconcile_one(project, force=force, summary=summary)
                await self._yield()
            after = page[-1].project_id
            if len(page) < self._batch_size:
                break
        return summary

    async def _reconcile_one(
        self,
        project: ProjectRef,
        *,
        force: bool,
        summary: ReconcileSummary,
    ) -> None:
        try:
            result = await self._rebuild_one(project, force)
        except Exception as exc:
            summary.failed += 1
            summary.failures.append((project.project_id, str(exc)[:_MAX_ERROR_LENGTH]))
            logger.warning(
                "Data catalog reconcile failed for project {}: {}", project.project_id, exc
            )
            return
        if result.status == "ok":
            summary.ok += 1
        elif result.status == "failed":
            summary.failed += 1
            summary.failures.append((project.project_id, (result.error or "")[:_MAX_ERROR_LENGTH]))
        else:
            summary.skipped += 1
