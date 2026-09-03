import sqlalchemy as sa
from cryptography.fernet import Fernet

from core.types import DBMetadata

from .dialects.clickhouse import load_clickhouse_metadata
from .dialects.mssql import load_mssql_metadata
from .dialects.mysql import load_mysql_metadata
from .dialects.oracle import load_oracle_metadata
from .dialects.postgres import load_postgresql_metadata
from .dialects.sqlite import load_sqlite_metadata
from .helpers import _rows_to_db_metadata, get_sa_type_for_dialect
from .table import load_db_table_metadata

__all__ = [
    'load_db_metadata',
    'load_db_table_metadata',
    'render_db_connection_string',
]


def render_db_connection_string(
    url: sa.URL | str,
    *,
    fernet_key: str | None = None,
) -> str:
    parsed_url = sa.make_url(url) if isinstance(url, str) else url
    if fernet_key and parsed_url.password:
        cipher = Fernet(fernet_key)
        encoded_password = cipher.encrypt(parsed_url.password.encode()).decode()
        parsed_url = parsed_url.set(password=encoded_password)
        return parsed_url.render_as_string(hide_password=False)
    return parsed_url.render_as_string(hide_password=True)


def load_db_metadata(engine: sa.Engine, fernet_key: str | None = None) -> DBMetadata:
    dialect_name = engine.dialect.name.lower()
    if dialect_name == "postgresql":
        db_metadata = load_postgresql_metadata(engine)
    elif dialect_name in ("mysql", "mariadb"):
        db_metadata = load_mysql_metadata(engine)
    elif dialect_name in ("mssql", "sqlserver"):
        db_metadata = load_mssql_metadata(engine)
    elif dialect_name == "clickhouse":
        db_metadata = load_clickhouse_metadata(engine)
    elif dialect_name == "sqlite":
        db_metadata = load_sqlite_metadata(engine)
    elif dialect_name == 'oracle':
        db_metadata = load_oracle_metadata(engine)
    else:
        raise NotImplementedError(f"Metadata loading for dialect '{dialect_name}' is not implemented")

    db_metadata.connection_string = render_db_connection_string(
        engine.url,
        fernet_key=fernet_key,
    )
    return db_metadata
