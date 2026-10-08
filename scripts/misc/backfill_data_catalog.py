"""Одноразовая сборка каталожных проекций для уже сохранённых проектов.

Запуск из корня репозитория через виртуальное окружение проекта:

    python -m scripts.misc.backfill_data_catalog [--project-id ID ...] [--organization-id ORG] [--dry-run]

Каждый проект обрабатывается в отдельной транзакции; ошибка одного проекта не останавливает
остальные и попадает в итоговую сводку.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field

os.environ.setdefault("SERVICE_NAME", "gateway")

import sqlalchemy as sa

from src.db import AsyncSessionLocal
from src.logger import logger
from src.modules.data_catalog import rebuild_project_catalog_projection
from src.modules.project.infra.db_models import ProjectRecord

import config  # noqa: F401


@dataclass
class BackfillSummary:
    total: int = 0
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


async def _list_projects(
    *,
    project_ids: list[str] | None,
    organization_id: str | None,
) -> list[tuple[str, str]]:
    statement = sa.select(ProjectRecord.id, ProjectRecord.organization_id).where(
        ProjectRecord.is_deleted.is_(False)
    )
    if project_ids:
        statement = statement.where(ProjectRecord.id.in_(project_ids))
    if organization_id:
        statement = statement.where(ProjectRecord.organization_id == organization_id)
    statement = statement.order_by(ProjectRecord.organization_id, ProjectRecord.id)
    async with AsyncSessionLocal() as session:
        return [tuple(row) for row in (await session.execute(statement)).all()]


async def backfill(
    *,
    project_ids: list[str] | None = None,
    organization_id: str | None = None,
    dry_run: bool = False,
) -> BackfillSummary:
    summary = BackfillSummary()
    projects = await _list_projects(project_ids=project_ids, organization_id=organization_id)
    summary.total = len(projects)
    logger.info("Data catalog backfill: {} project(s) selected (dry_run={})", len(projects), dry_run)

    for project_id, org_id in projects:
        if dry_run:
            summary.skipped += 1
            continue
        async with AsyncSessionLocal() as session:
            try:
                result = await rebuild_project_catalog_projection(
                    session=session,
                    project_id=project_id,
                    organization_id=org_id,
                    force=True,
                    raise_on_error=True,
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                summary.failed += 1
                summary.failures.append((project_id, str(exc)[:200]))
                logger.warning("Data catalog backfill failed for project {}: {}", project_id, exc)
                continue
        if result.status == "ok":
            summary.ok += 1
        else:
            summary.skipped += 1

    logger.info(
        "Data catalog backfill done: total={} ok={} skipped={} failed={}",
        summary.total,
        summary.ok,
        summary.skipped,
        summary.failed,
    )
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Data Catalog projections.")
    parser.add_argument("--project-id", action="append", dest="project_ids", default=None)
    parser.add_argument("--organization-id", dest="organization_id", default=None)
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    summary = asyncio.run(
        backfill(
            project_ids=args.project_ids,
            organization_id=args.organization_id,
            dry_run=args.dry_run,
        )
    )
    for project_id, error in summary.failures:
        print(f"FAILED {project_id}: {error}")
    print(
        f"total={summary.total} ok={summary.ok} skipped={summary.skipped} failed={summary.failed}"
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
