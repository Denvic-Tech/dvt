from typing import Optional

import sqlalchemy.ext.asyncio as asa
from cryptography.fernet import Fernet

from core.types import DBMetadata

from .clickhouse import load_clickhouse_metadata
from .mssql import load_mssql_metadata
from .mysql import load_mysql_metadata
from .oracle import load_oracle_metadata
from .postgres import load_postgresql_metadata
from .sqlite import load_sqlite_metadata


async def load_db_metadata(engine: asa.AsyncEngine, fernet_key: Optional[str] = None) -> DBMetadata:
    dialect_name = engine.dialect.name.lower()
    if dialect_name == "postgresql":
        db_metadata = await load_postgresql_metadata(engine)
    elif dialect_name in ("mysql", "mariadb"):
        db_metadata = await load_mysql_metadata(engine)
    elif dialect_name in ("mssql", "sqlserver"):
        db_metadata = await load_mssql_metadata(engine)
    elif dialect_name == "clickhouse":
        db_metadata = await load_clickhouse_metadata(engine)
    elif dialect_name == "sqlite":
        db_metadata = await load_sqlite_metadata(engine)
    elif dialect_name == 'oracle':
        db_metadata = await load_oracle_metadata(engine)
    else:
        raise NotImplementedError(f"Metadata loading for dialect '{dialect_name}' is not implemented")

    if fernet_key and engine.url.password:
        cipher = Fernet(fernet_key)
        password = engine.url.password.encode()
        encoded_password = cipher.encrypt(password).decode()
        url = engine.url.set(password=encoded_password)
        connection_string = url.render_as_string(hide_password=False)
    else:
        connection_string = engine.url.render_as_string(hide_password=True)

    db_metadata.connection_string = connection_string
    return db_metadata
