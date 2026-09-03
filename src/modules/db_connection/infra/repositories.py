from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from db_connection import StoredConnectionRecordMapper
from db_connection.domain import ConnectionDraft, ConnectionListQuery, ConnectionRecord
from db_connection.domain.drivers import DriverOptionsBase
from db_connection.domain.repositories import ConnectionRepository
from db_connection.errors import ValidationFailedError
from db_connection.runtime.encryption import EncryptionProvider, NoOpEncryptionProvider
from sqlalchemy.ext.asyncio import AsyncSession

from .db_models import DVTStoredConnectionRecord


class DVTConnectionRepository(ConnectionRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        encryption_provider: EncryptionProvider | None = None,
    ) -> None:
        self.session = session
        self._encryption_provider = encryption_provider or NoOpEncryptionProvider()
        self._record_mapper = StoredConnectionRecordMapper(encryption_provider=encryption_provider)

    async def create(self, draft: ConnectionDraft) -> ConnectionRecord:
        now = datetime.now(UTC)
        owner_fields = self._extract_owner_fields(draft.extra)
        row = DVTStoredConnectionRecord(
            id=str(uuid4()),
            name=draft.name,
            kind=draft.kind,
            type=draft.type,
            driver=draft.driver,
            driver_options_json=draft.driver_options,
            properties_json=draft.properties,
            secrets_ciphertext=self._encryption_provider.encrypt(draft.secrets),
            labels_json=draft.labels,
            metadata_json=draft.metadata,
            extra_json=draft.extra,
            created_at=now,
            updated_at=now,
            user_id=owner_fields["user_id"],
            organization_id=owner_fields["organization_id"],
        )
        self.session.add(row)
        await self.session.flush()
        return self._to_record(row)

    async def list(self, query: ConnectionListQuery) -> list[ConnectionRecord]:
        statement = sa.select(DVTStoredConnectionRecord)
        if not query.include_deleted:
            statement = statement.where(DVTStoredConnectionRecord.deleted_at.is_(None))
        if query.kind is not None:
            statement = statement.where(DVTStoredConnectionRecord.kind == query.kind)
        if query.type is not None:
            statement = statement.where(DVTStoredConnectionRecord.type == query.type)
        if query.name is not None:
            statement = statement.where(DVTStoredConnectionRecord.name.contains(query.name))

        rows = (await self.session.execute(statement)).scalars().all()
        rows = [row for row in rows if self._matches_filters(row, query)]
        return [self._to_record(row) for row in rows]

    async def get(self, connection_id: str) -> ConnectionRecord | None:
        row = await self.session.get(DVTStoredConnectionRecord, connection_id)
        return None if row is None else self._to_record(row)

    async def replace(self, connection_id: str, draft: ConnectionDraft) -> ConnectionRecord | None:
        row = await self.session.get(DVTStoredConnectionRecord, connection_id)
        if row is None:
            return None

        owner_fields = self._extract_owner_fields(draft.extra)
        row.name = draft.name
        row.kind = draft.kind
        row.type = draft.type
        row.driver = draft.driver
        row.driver_options_json = draft.driver_options
        row.properties_json = draft.properties
        row.secrets_ciphertext = self._encryption_provider.encrypt(draft.secrets)
        row.labels_json = draft.labels
        row.metadata_json = draft.metadata
        row.extra_json = draft.extra
        row.user_id = owner_fields["user_id"]
        row.organization_id = owner_fields["organization_id"]
        row.updated_at = datetime.now(UTC)
        self.session.add(row)
        await self.session.flush()
        return self._to_record(row)

    async def delete(self, connection_id: str) -> ConnectionRecord | None:
        row = await self.session.get(DVTStoredConnectionRecord, connection_id)
        if row is None:
            return None

        row.deleted_at = datetime.now(UTC)
        row.updated_at = row.deleted_at
        self.session.add(row)
        await self.session.flush()
        return self._to_record(row)

    def _to_record(self, row: DVTStoredConnectionRecord) -> ConnectionRecord:
        extra = dict(row.extra_json or {})
        extra["organization_id"] = row.organization_id
        extra["user_id"] = row.user_id

        return self._record_mapper.to_record(
            id=row.id,
            name=row.name,
            kind=row.kind,
            type=row.type,
            driver=row.driver,
            driver_options_json=self._driver_options_json_for_mapper(row.driver_options_json),
            properties_json=row.properties_json,
            secrets_ciphertext=row.secrets_ciphertext,
            labels_json=row.labels_json,
            metadata_json=row.metadata_json,
            extra=extra,
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
        )

    def _matches_filters(self, row: DVTStoredConnectionRecord, query: ConnectionListQuery) -> bool:
        return (
            self._matches_mapping_filters(row, row.labels_json, query.label_filters)
            and self._matches_mapping_filters(row, row.metadata_json, query.metadata_filters)
            and self._matches_mapping_filters(row, row.extra_json, query.extra_filters)
        )

    def _matches_mapping_filters(
        self,
        row: DVTStoredConnectionRecord,
        values: dict[str, object],
        filters: dict[str, object],
    ) -> bool:
        for key, value in filters.items():
            if key == "organization_id" and row.organization_id != value:
                return False
            if key == "user_id" and row.user_id != value:
                return False
            if key not in {"organization_id", "user_id"} and values.get(key) != value:
                return False
        return True

    @staticmethod
    def _extract_owner_fields(extra: dict[str, object]) -> dict[str, str]:
        user_id = extra.get("user_id")
        organization_id = extra.get("organization_id")

        if not isinstance(user_id, str) or not user_id:
            raise ValidationFailedError("Connection user_id is required.")
        if not isinstance(organization_id, str) or not organization_id:
            raise ValidationFailedError("Connection organization_id is required.")

        return {
            "user_id": user_id,
            "organization_id": organization_id,
        }

    @staticmethod
    def _driver_options_json_for_mapper(value: object) -> object:
        if isinstance(value, DriverOptionsBase):
            model_type = type(value)
            return {
                "model_ref": f"{model_type.__module__}:{model_type.__qualname__}",
                "data": value.model_dump(mode="json"),
            }
        return value
