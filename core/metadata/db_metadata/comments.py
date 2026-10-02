"""Normalization and best-effort reflection of optional database comments."""

import logging

import sqlalchemy as sa

logger = logging.getLogger(__name__)


def normalize_comment(value: object) -> str | None:
    return None if value is None or value == "" else str(value)


def load_table_comment(
    inspector: sa.Inspector,
    table_name: str,
    *,
    schema_name: str | None = None,
) -> str | None:
    try:
        reflected = inspector.get_table_comment(table_name, schema=schema_name) or {}
        comment = normalize_comment(reflected.get("text"))
        if comment is None and inspector.dialect.name == "mssql":
            # SQLAlchemy asks fn_listextendedproperty for TABLE, which omits VIEW comments.
            with inspector.engine.connect() as connection:
                comment = normalize_comment(
                    connection.execute(
                        sa.text("""
                    SELECT CAST(ep.value AS NVARCHAR(max))
                    FROM sys.objects o
                    JOIN sys.schemas s ON s.schema_id = o.schema_id
                    JOIN sys.extended_properties ep
                      ON ep.class = 1 AND ep.major_id = o.object_id AND ep.minor_id = 0
                     AND ep.name = 'MS_Description'
                    WHERE o.type = 'V' AND o.name = :name
                      AND s.name = COALESCE(:schema, SCHEMA_NAME())
                """),
                        {"name": table_name, "schema": schema_name},
                    ).scalar()
                )
    except NotImplementedError:
        return None
    except (sa.exc.SQLAlchemyError, OSError):
        # Driver exceptions can include credentials, SQL and user-controlled text.
        logger.warning("Unable to read optional database table comment.")
        return None
    else:
        return comment
