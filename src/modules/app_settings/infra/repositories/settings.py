from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.app_settings.domain.entities import SettingChange, SettingValue
from src.modules.app_settings.domain.registry import SettingsRegistry
from src.modules.app_settings.domain.repositories import AppSettingsRepository
from src.modules.app_settings.infra.db_models import AppSettingChangeRecord, AppSettingValueRecord
from src.modules.app_settings.infra.encryption import FernetSettingValueCipher
from src.modules.app_settings.infra.mappers import (
    SettingValueCodec,
    change_row_to_domain,
    value_row_to_domain,
)


class SQLAppSettingsRepository(AppSettingsRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: type[SettingsRegistry],
        cipher: FernetSettingValueCipher,
        codec: SettingValueCodec | None = None,
    ) -> None:
        self.session = session
        self.registry = registry
        self.cipher = cipher
        self.codec = codec or SettingValueCodec()

    async def get_values(self, keys: Iterable[str]) -> dict[str, SettingValue]:
        key_list = list(keys)
        if not key_list:
            return {}
        statement = sa.select(AppSettingValueRecord).where(AppSettingValueRecord.key.in_(key_list))
        rows = (await self.session.execute(statement)).scalars().all()
        return {
            row.key: value_row_to_domain(
                row,
                definition=self.registry.get_definition(row.key),
                registry=self.registry,
                codec=self.codec,
                decrypt_value=self.cipher.decrypt,
            )
            for row in rows
            if self.registry.contains(row.key)
        }

    async def save(
        self,
        value: SettingValue,
        *,
        changed_by: str | None = None,
        change_reason: str | None = None,
    ) -> SettingValue:
        definition = self.registry.get_definition(value.key)
        now = datetime.now(UTC)
        row = (
            await self.session.execute(
                sa.select(AppSettingValueRecord).where(AppSettingValueRecord.key == value.key)
            )
        ).scalars().first()

        old_payload = row.value if row is not None else None
        new_payload = self.cipher.encrypt(self.codec.dumps(value.value), definition=definition)
        version = 1 if row is None else row.version + 1

        if row is None:
            row = AppSettingValueRecord(
                key=value.key,
                value=new_payload,
                version=version,
                updated_at=now,
                updated_by=changed_by,
            )
        else:
            row.value = new_payload
            row.version = version
            row.updated_at = now
            row.updated_by = changed_by

        self.session.add(row)
        self.session.add(
            AppSettingChangeRecord(
                key=value.key,
                old_value=old_payload,
                new_value=new_payload,
                changed_at=now,
                changed_by=changed_by,
                change_reason=change_reason,
            )
        )
        await self.session.flush()
        return SettingValue(
            key=value.key,
            value=value.value,
            version=version,
            updated_at=now,
            updated_by=changed_by,
        )

    async def delete(
        self,
        key: str,
        *,
        changed_by: str | None = None,
        change_reason: str | None = None,
    ) -> SettingChange | None:
        self.registry.get_definition(key)
        row = (
            await self.session.execute(sa.select(AppSettingValueRecord).where(AppSettingValueRecord.key == key))
        ).scalars().first()
        if row is None:
            return None

        now = datetime.now(UTC)
        change_row = AppSettingChangeRecord(
            key=key,
            old_value=row.value,
            new_value=None,
            changed_at=now,
            changed_by=changed_by,
            change_reason=change_reason,
        )
        self.session.add(change_row)
        await self.session.delete(row)
        await self.session.flush()
        return change_row_to_domain(
            change_row,
            definition=self.registry.get_definition(key),
            registry=self.registry,
            codec=self.codec,
            decrypt_value=self.cipher.decrypt,
        )

    async def get_history(self, key: str) -> list[SettingChange]:
        definition = self.registry.get_definition(key)
        statement = (
            sa.select(AppSettingChangeRecord)
            .where(AppSettingChangeRecord.key == key)
            .order_by(AppSettingChangeRecord.changed_at.desc())
        )
        rows = (await self.session.execute(statement)).scalars().all()
        return [
            change_row_to_domain(
                row,
                definition=definition,
                registry=self.registry,
                codec=self.codec,
                decrypt_value=self.cipher.decrypt,
            )
            for row in rows
        ]
