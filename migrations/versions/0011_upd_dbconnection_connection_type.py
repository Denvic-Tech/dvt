"""UPD DBConnection connection_type

Revision ID: 0011
Revises: 0010
Create Date: 2025-11-09 12:29:33.637854

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Старый enum (из миграции 0002) - ВЕРХНИЙ регистр (так в базе)
OLD_ENUM = postgresql.ENUM(
    "MYSQL", "POSTGRES", "CLICKHOUSE", "MONGODB", "MSSQL", "KAFKA",
    name="connectiontype",
)

# Новый enum - нижний регистр + добавлены s3 и custom
NEW_ENUM = postgresql.ENUM(
    "mysql", "postgres", "clickhouse", "mongodb", "mssql", "kafka", "s3", "custom",
    name="connectiontype_new",
)


def upgrade() -> None:
    """Upgrade schema: меняем регистр enum на нижний и добавляем S3 и CUSTOM."""
    bind = op.get_bind()

    # 1. Создаём новый enum с нижним регистром и дополнительными значениями
    NEW_ENUM.create(bind, checkfirst=True)

    # 2. Меняем тип колонки на новый enum с преобразованием регистра
    #    LOWER(type::text) конвертирует POSTGRES -> postgres
    op.execute("""
        ALTER TABLE db_connections
        ALTER COLUMN type TYPE connectiontype_new
        USING LOWER(type::text)::connectiontype_new
    """)

    # 3. Удаляем старый enum
    OLD_ENUM.drop(bind, checkfirst=True)

    # 4. Переименовываем новый enum в старое имя
    op.execute("ALTER TYPE connectiontype_new RENAME TO connectiontype")


def downgrade() -> None:
    """Downgrade schema: возвращаем регистр enum в ВЕРХНИЙ и убираем S3 и CUSTOM.

    ВАЖНО: Если в базе есть записи с type='s3' или type='custom',
    они будут потеряны при откате миграции!
    """
    bind = op.get_bind()

    # Проверяем, есть ли записи с новыми типами
    result = bind.execute(sa.text(
        "SELECT COUNT(*) FROM db_connections WHERE type IN ('s3', 'custom')"
    )).scalar()

    if result > 0:
        raise ValueError(
            f"Cannot downgrade: {result} connection(s) with type 's3' or 'custom' exist. "
            "Please delete or update these connections before downgrading."
        )

    # 1. Переименовываем текущий enum
    op.execute("ALTER TYPE connectiontype RENAME TO connectiontype_new")

    # 2. Создаём старый enum (с ВЕРХНИМ регистром)
    OLD_ENUM.create(bind, checkfirst=True)

    # 3. Меняем тип колонки обратно на старый enum с преобразованием регистра
    #    UPPER(type::text) конвертирует postgres -> POSTGRES
    op.execute("""
        ALTER TABLE db_connections
        ALTER COLUMN type TYPE connectiontype
        USING UPPER(type::text)::connectiontype
    """)

    # 4. Удаляем новый enum
    NEW_ENUM.drop(bind, checkfirst=True)
