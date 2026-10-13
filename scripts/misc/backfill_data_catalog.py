"""Ручная сборка каталожных проекций для уже сохранённых проектов.

Gateway сам сверяет проекции при старте (только устаревшие), поэтому скрипт нужен для
принудительной пересборки или точечной диагностики. Запуск из корня репозитория через
виртуальное окружение проекта:

    python -m scripts.misc.backfill_data_catalog [--project-id ID ...] [--organization-id ORG]
                                                 [--stale-only] [--batch-size N] [--dry-run]

По умолчанию пересобираются все выбранные проекты; --stale-only ограничивает выбор
проектами без проекции или с устаревшим штампом. Каждый проект обрабатывается в отдельной
транзакции; ошибка одного проекта не останавливает остальные и попадает в итоговую сводку.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

os.environ.setdefault("SERVICE_NAME", "gateway")

from src.db import AsyncSessionLocal
from src.modules.data_catalog import reconcile_catalog_projections
from src.modules.data_catalog.domain import ReconcileSummary

import config  # noqa: F401


async def backfill(
    *,
    project_ids: list[str] | None = None,
    organization_id: str | None = None,
    stale_only: bool = False,
    batch_size: int = 100,
    dry_run: bool = False,
) -> ReconcileSummary:
    return await reconcile_catalog_projections(
        session_factory=AsyncSessionLocal,
        force=not stale_only,
        dry_run=dry_run,
        batch_size=batch_size,
        organization_id=organization_id,
        project_ids=project_ids,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Data Catalog projections.")
    parser.add_argument("--project-id", action="append", dest="project_ids", default=None)
    parser.add_argument("--organization-id", dest="organization_id", default=None)
    parser.add_argument("--stale-only", action="store_true", dest="stale_only")
    parser.add_argument("--batch-size", type=int, dest="batch_size", default=100)
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
            stale_only=args.stale_only,
            batch_size=args.batch_size,
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
