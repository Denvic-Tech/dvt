"""ADD new DBConnection V1 model

Revision ID: 0054
Revises: 0053
Create Date: 2026-06-01 10:53:08.787002

"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Union

from alembic import op
from cryptography.fernet import Fernet, InvalidToken
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from db_connection.domain.drivers import ODBCDriverOptions
import db_connection.infra.sa_types
import config

# revision identifiers, used by Alembic.
revision: str = '0054'
down_revision: Union[str, Sequence[str], None] = '0053'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_FERNET_PREFIX = "fernet$"
SQL_CONNECTION_TYPES = frozenset({"postgres", "mysql", "clickhouse", "mongodb", "mssql", "oracle"})
PASSWORD_SECRET_KEYS = ("password",)
KAFKA_SECRET_KEYS = ("sasl_plain_password",)
S3_SECRET_KEYS = ("access_token_id", "access_token_key", "session_token")
SFTP_SECRET_KEYS = ("password", "private_key_passphrase", "private_key_string")

LEGACY_DB_CONNECTIONS = sa.table(
    "db_connections",
    sa.column("id", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("name", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("type", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("connection_properties", sa.JSON()),
    sa.column("created_at", sa.DateTime()),
    sa.column("updated_at", sa.DateTime()),
    sa.column("is_deleted", sa.Boolean()),
    sa.column("user_id", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("organization_id", sqlmodel.sql.sqltypes.AutoString()),
)

CONNECTIONS_V1 = sa.table(
    "connections_v1",
    sa.column("id", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("name", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("kind", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("type", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("driver", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("driver_options_json", db_connection.infra.sa_types.DriverOptionsType()),
    sa.column("properties_json", sa.JSON()),
    sa.column("secrets_ciphertext", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("labels_json", sa.JSON()),
    sa.column("metadata_json", sa.JSON()),
    sa.column("extra_json", sa.JSON()),
    sa.column("created_at", sa.DateTime()),
    sa.column("updated_at", sa.DateTime()),
    sa.column("deleted_at", sa.DateTime()),
    sa.column("user_id", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("organization_id", sqlmodel.sql.sqltypes.AutoString()),
)


def _get_fernet() -> Fernet:
    key = config.SECURITY.FERNET_KEY
    if not key:
        raise RuntimeError("FERNET_KEY is not configured.")
    key_bytes = key.encode("utf-8") if isinstance(key, str) else key
    return Fernet(key_bytes)


def _decrypt_legacy_secret(value: Any, cipher: Fernet) -> Any:
    if not isinstance(value, str) or not value.startswith(LEGACY_FERNET_PREFIX):
        return value

    token = value[len(LEGACY_FERNET_PREFIX):].encode("utf-8")
    try:
        return cipher.decrypt(token).decode("utf-8")
    except InvalidToken:
        return value


def _encrypt_runtime_secrets(payload: dict[str, Any], cipher: Fernet) -> str:
    raw = json.dumps(payload).encode("utf-8")
    return cipher.encrypt(raw).decode("utf-8")


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if value is not None
    }


def _extract_secrets(
    *,
    raw: dict[str, Any],
    secret_keys: tuple[str, ...],
    cipher: Fernet,
    values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    secret_values = {} if values is None else dict(values)
    for secret_key in secret_keys:
        if secret_key not in secret_values:
            secret_values[secret_key] = raw.pop(secret_key, None)

    return _drop_none(
        {
            key: _decrypt_legacy_secret(value, cipher)
            for key, value in secret_values.items()
        }
    )


def _build_connection_data(
    properties: dict[str, Any],
    secrets: dict[str, Any],
    driver: str | None,
    driver_options: ODBCDriverOptions | None,
) -> tuple[dict[str, Any], dict[str, Any], str | None, ODBCDriverOptions | None]:
    return properties, secrets, driver, driver_options


def _split_connection_data(
    connection_type: str,
    properties: Mapping[str, Any],
    *,
    cipher: Fernet,
) -> tuple[str, dict[str, Any], dict[str, Any], str | None, ODBCDriverOptions | None]:
    normalized_type = connection_type.lower()
    raw = dict(properties)

    if normalized_type in SQL_CONNECTION_TYPES:
        legacy_driver_name = raw.pop("driver_name", None)
        password = raw.pop("password", None)
        driver_options = None

        if normalized_type == "mssql":
            driver = "pyodbc" if legacy_driver_name else None
            if legacy_driver_name:
                driver_options = ODBCDriverOptions(odbc_driver_name=legacy_driver_name)
        else:
            driver = legacy_driver_name
            if normalized_type == "clickhouse" and driver is None:
                driver = "http"

        sql_secrets = _extract_secrets(
            raw={},
            secret_keys=PASSWORD_SECRET_KEYS,
            cipher=cipher,
            values={"password": password},
        )
        properties_json, secrets_json, driver, driver_options = _build_connection_data(
            raw,
            sql_secrets,
            driver,
            driver_options,
        )
        return "sql", properties_json, secrets_json, driver, driver_options

    if normalized_type == "kafka":
        password = raw.pop("sasl_plain_password", None)
        kafka_secrets = _extract_secrets(
            raw={},
            secret_keys=KAFKA_SECRET_KEYS,
            cipher=cipher,
            values={"sasl_plain_password": password},
        )
        properties_json, secrets_json, driver, driver_options = _build_connection_data(
            raw,
            kafka_secrets,
            None,
            None,
        )
        return "queue", properties_json, secrets_json, driver, driver_options

    if normalized_type == "s3":
        secrets = _extract_secrets(raw=raw, secret_keys=S3_SECRET_KEYS, cipher=cipher)
        properties_json, secrets_json, driver, driver_options = _build_connection_data(
            raw,
            secrets,
            None,
            None,
        )
        return "file", properties_json, secrets_json, driver, driver_options

    if normalized_type == "ftp":
        password = raw.pop("password", None)
        ftp_secrets = _extract_secrets(
            raw={},
            secret_keys=PASSWORD_SECRET_KEYS,
            cipher=cipher,
            values={"password": password},
        )
        properties_json, secrets_json, driver, driver_options = _build_connection_data(
            raw,
            ftp_secrets,
            None,
            None,
        )
        return "file", properties_json, secrets_json, driver, driver_options

    if normalized_type == "sftp":
        secrets = _extract_secrets(raw=raw, secret_keys=SFTP_SECRET_KEYS, cipher=cipher)
        properties_json, secrets_json, driver, driver_options = _build_connection_data(
            raw,
            secrets,
            None,
            None,
        )
        return "file", properties_json, secrets_json, driver, driver_options

    return "custom", raw, {}, None, None


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _build_deleted_at(*, is_deleted: bool | None, updated_at: datetime | None) -> datetime | None:
    if not is_deleted:
        return None
    return updated_at


def _migrate_legacy_db_connections() -> None:
    bind = op.get_bind()
    cipher = _get_fernet()
    rows = bind.execute(
        sa.select(
            LEGACY_DB_CONNECTIONS.c.id,
            LEGACY_DB_CONNECTIONS.c.name,
            LEGACY_DB_CONNECTIONS.c.type,
            LEGACY_DB_CONNECTIONS.c.connection_properties,
            LEGACY_DB_CONNECTIONS.c.created_at,
            LEGACY_DB_CONNECTIONS.c.updated_at,
            LEGACY_DB_CONNECTIONS.c.is_deleted,
            LEGACY_DB_CONNECTIONS.c.user_id,
            LEGACY_DB_CONNECTIONS.c.organization_id,
        )
    ).mappings()

    payloads = []
    for row in rows:
        kind, properties_json, secrets_json, driver, driver_options = _split_connection_data(
            str(row["type"]),
            _coerce_mapping(row["connection_properties"]),
            cipher=cipher,
        )
        payloads.append(
            {
                "id": row["id"],
                "name": row["name"],
                "kind": kind,
                "type": str(row["type"]).lower(),
                "driver": driver,
                "driver_options_json": driver_options,
                "properties_json": properties_json,
                "secrets_ciphertext": _encrypt_runtime_secrets(secrets_json, cipher),
                "labels_json": {},
                "metadata_json": {},
                "extra_json": {
                    "user_id": row["user_id"],
                    "organization_id": row["organization_id"],
                },
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "deleted_at": _build_deleted_at(
                    is_deleted=row["is_deleted"],
                    updated_at=row["updated_at"],
                ),
                "user_id": row["user_id"],
                "organization_id": row["organization_id"],
            }
        )

    if payloads:
        bind.execute(sa.insert(CONNECTIONS_V1), payloads)


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('connections_v1',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('driver', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('driver_options_json', db_connection.infra.sa_types.DriverOptionsType(), nullable=True),
    sa.Column('properties_json', sa.JSON(), nullable=False),
    sa.Column('secrets_ciphertext', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('labels_json', sa.JSON(), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=False),
    sa.Column('extra_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('organization_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_connections_v1_kind'), 'connections_v1', ['kind'], unique=False)
    op.create_index(op.f('ix_connections_v1_name'), 'connections_v1', ['name'], unique=False)
    op.create_index(op.f('ix_connections_v1_organization_id'), 'connections_v1', ['organization_id'], unique=False)
    op.create_index(op.f('ix_connections_v1_type'), 'connections_v1', ['type'], unique=False)
    _migrate_legacy_db_connections()
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_connections_v1_type'), table_name='connections_v1')
    op.drop_index(op.f('ix_connections_v1_organization_id'), table_name='connections_v1')
    op.drop_index(op.f('ix_connections_v1_name'), table_name='connections_v1')
    op.drop_index(op.f('ix_connections_v1_kind'), table_name='connections_v1')
    op.drop_table('connections_v1')
    # ### end Alembic commands ###
