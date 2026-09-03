"""UPD db-connections model

Revision ID: 0002
Revises: 0001
Create Date: 2025-08-08 18:10:36.564435

"""
from typing import Sequence, Union, Any
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


JSONB = postgresql.JSONB(astext_type=sa.Text())

NEW_ENUM = postgresql.ENUM(
    "MYSQL", "POSTGRES", "CLICKHOUSE", "MONGODB", "MSSQL", "KAFKA",
    name="connectiontype",
)
OLD_ENUM = postgresql.ENUM(
    "MYSQL", "POSTGRES", "CLICKHOUSE",
    name="databaseconnectiontype",
)

_EXTRA = (
    "secure", "connect_timeout", "send_receive_timeout",
    "sync_request_timeout", "ca_cert_string", "verify", "driver_name",
)


def _merge(row: Any) -> dict:
    data = {
        "host": row.host,
        "port": row.port,
        "username": row.username,
        "password": row.password,
        "database": row.database,
    }
    ap = row.additional_properties or {}
    if isinstance(ap, str):
        try:
            ap = json.loads(ap)
        except Exception:
            ap = {}
    for k in _EXTRA:
        if k in ap:
            data[k] = ap[k]
    return data


# ───────────── upgrade ─────────────────────────────────────────────────────────
def upgrade() -> None:
    bind = op.get_bind()

    # 0. страховка: убрать хвосты старых неудачных прогонов
    op.execute("ALTER TABLE db_connections DROP COLUMN IF EXISTS connection_properties")
    NEW_ENUM.drop(bind, checkfirst=True)

    # 1. enum
    NEW_ENUM.create(bind)

    # 2. новая колонка
    op.add_column("db_connections", sa.Column("connection_properties", JSONB, nullable=True))

    # 3. миграция данных
    t = sa.table(
        "db_connections",
        sa.column("id", sa.Integer()),
        sa.column("host", sa.String()),
        sa.column("port", sa.Integer()),
        sa.column("username", sa.String()),
        sa.column("password", sa.String()),
        sa.column("database", sa.String()),
        sa.column("additional_properties", JSONB),
    )
    rows = bind.execute(sa.select(t)).fetchall()
    q = sa.text("""
        UPDATE db_connections
           SET connection_properties = CAST(:v AS jsonb)
         WHERE id = :id
    """)
    for r in rows:
        bind.execute(q, {"v": json.dumps(_merge(r)), "id": r.id})
    # bind.commit()

    # 4. смена типа enum
    op.alter_column(
        "db_connections", "type",
        existing_type=OLD_ENUM,
        type_=NEW_ENUM,
        postgresql_using="type::text::connectiontype",
    )

    # 5. прямое удаление старых колонок
    op.execute("""
        ALTER TABLE db_connections
          DROP COLUMN IF EXISTS host,
          DROP COLUMN IF EXISTS port,
          DROP COLUMN IF EXISTS username,
          DROP COLUMN IF EXISTS password,
          DROP COLUMN IF EXISTS database,
          DROP COLUMN IF EXISTS additional_properties,
          DROP COLUMN IF EXISTS options
    """)

    # 6. NOT NULL
    op.alter_column("db_connections", "connection_properties", nullable=False)

    op.add_column(
        "db_connections",
        sa.Column("is_deleted", sa.Boolean(), nullable=True)
    )

    # проставить значения существующим строкам
    op.execute("UPDATE db_connections SET is_deleted = FALSE WHERE is_deleted IS NULL;")

    # запретить NULL
    op.alter_column(
        "db_connections",
        "is_deleted",
        nullable=False,
        existing_type=sa.Boolean(),
    )

    # дропнуть старое поле
    op.drop_column("db_connections", "is_active")
    


# ───────────── downgrade ───────────────────────────────────────────────────────
def downgrade() -> None:
    bind = op.get_bind()

    # 1. вернуть старые колонны
    op.add_column("db_connections", sa.Column("host", sa.String(255), nullable=True))
    op.add_column("db_connections", sa.Column("port", sa.Integer(), nullable=True))
    op.add_column("db_connections", sa.Column("username", sa.String(100), nullable=True))
    op.add_column("db_connections", sa.Column("password", sa.String(100), nullable=True))
    op.add_column("db_connections", sa.Column("database", sa.String(255), nullable=True))
    op.add_column("db_connections", sa.Column("additional_properties", postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column("db_connections", sa.Column("options", sa.Text(), nullable=True))

    # 2. enum назад
    OLD_ENUM.create(bind, checkfirst=True)
    op.alter_column(
        "db_connections", "type",
        existing_type=NEW_ENUM,
        type_=OLD_ENUM,
        postgresql_using="type::text::databaseconnectiontype",
    )

    # 3. раскатить данные обратно (упрощённо)
    t = sa.table(
        "db_connections",
        sa.column("id", sa.Integer()),
        sa.column("connection_properties", JSONB),
    )
    rows = bind.execute(sa.select(t)).fetchall()
    q = sa.text("""
        UPDATE db_connections
           SET host=:h, port=:p, username=:u,
               password=:pw, database=:db,
               additional_properties=CAST(:ap AS jsonb)
         WHERE id=:id
    """)
    for r in rows:
        cp = r.connection_properties or {}
        if isinstance(cp, str):
            cp = json.loads(cp)
        ap = {k: cp.get(k) for k in _EXTRA if k in cp}
        bind.execute(q, {
            "h": cp.get("host"), "p": cp.get("port"), "u": cp.get("username"),
            "pw": cp.get("password"), "db": cp.get("database"),
            "ap": json.dumps(ap),
            "id": r.id,
        })

    # 4. убрать новую колонку и enum
    op.drop_column("db_connections", "connection_properties")
    NEW_ENUM.drop(bind, checkfirst=True)

    op.add_column("db_connections", sa.Column("is_active", sa.Boolean(), nullable=True))
    op.execute("""
               UPDATE db_connections
               SET is_active = TRUE
               """
               )
    op.drop_column("db_connections", "is_deleted")
