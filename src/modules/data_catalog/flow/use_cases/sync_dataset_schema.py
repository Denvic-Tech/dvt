from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.logger import logger

from ...domain import (
    CatalogViewer,
    CheckErrorKind,
    Dataset,
    DatasetConnectionRepository,
    DatasetFieldRepository,
    DatasetRepository,
    DatasetSchemaSource,
    FieldStatus,
    SchemaActor,
    SchemaSourceNotFoundError,
    SchemaSourceUnavailableError,
    SyncOutcome,
)
from ...domain.policies import merge_observed_fields

_MAX_ERROR_LENGTH = 500


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class SyncDatasetSchema:
    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        fields: DatasetFieldRepository,
        connections: DatasetConnectionRepository,
        schema_source: DatasetSchemaSource,
        ttl_seconds: int,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._datasets = datasets
        self._fields = fields
        self._connections = connections
        self._source = schema_source
        self._ttl = timedelta(seconds=max(ttl_seconds, 0))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._new_id = id_factory or (lambda: str(uuid4()))

    async def execute(
        self,
        *,
        dataset: Dataset,
        viewer: CatalogViewer,
        actor: SchemaActor,
        force: bool = False,
        bypass_cache: bool = False,
    ) -> SyncOutcome:
        now = self._clock()
        if (
            not force
            and dataset.schema_synced_at is not None
            and _aware(now) - _aware(dataset.schema_synced_at) <= self._ttl
        ):
            return SyncOutcome(status="skipped")

        connection_ids = await self._connections.list_usable_connection_ids(dataset.id, viewer)
        if not connection_ids:
            return SyncOutcome(status="no_connection")

        observed = None
        last_error: str | None = None
        last_error_kind: CheckErrorKind | None = None
        used_connection: str | None = None
        for connection_id in connection_ids:
            try:
                observed = await self._source.fetch_fields(
                    connection_id=connection_id,
                    actor=actor,
                    database=dataset.locator.database,
                    schema=dataset.locator.schema,
                    table=dataset.locator.table,
                    bypass_cache=bypass_cache,
                )
                used_connection = connection_id
                break
            except SchemaSourceUnavailableError as exc:
                last_error = str(exc)[:_MAX_ERROR_LENGTH]
                last_error_kind = (
                    CheckErrorKind.NOT_FOUND
                    if isinstance(exc, SchemaSourceNotFoundError)
                    else CheckErrorKind.UNREACHABLE
                )
                logger.warning(
                    "Dataset {} schema sync via connection {} failed ({}): {}",
                    dataset.id,
                    connection_id,
                    last_error_kind.value,
                    exc,
                )

        if observed is None or used_connection is None:
            dataset.last_check_failed_at = now
            dataset.last_check_error = last_error
            dataset.last_check_error_kind = last_error_kind
            dataset.updated_at = now
            await self._datasets.update(dataset)
            return SyncOutcome(status="failed", error=last_error, error_kind=last_error_kind)

        existing = await self._fields.list_for_dataset(dataset.id)
        merged = merge_observed_fields(
            dataset_id=dataset.id,
            existing=existing,
            observed=observed,
            connection_id=used_connection,
            now=now,
            new_id=self._new_id,
        )
        await self._fields.save_many(merged)

        dataset.schema_synced_at = now
        dataset.last_check_error = None
        dataset.last_check_error_kind = None
        dataset.updated_at = now
        await self._datasets.update(dataset)

        return SyncOutcome(
            status="synced",
            new=sum(1 for field in merged if field.status is FieldStatus.NEW),
            missing=sum(1 for field in merged if field.status is FieldStatus.MISSING),
            type_changed=sum(1 for field in merged if field.status is FieldStatus.TYPE_CHANGED),
            fields=tuple(merged),
        )
