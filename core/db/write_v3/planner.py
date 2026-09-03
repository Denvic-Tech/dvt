from __future__ import annotations

import sqlalchemy as sa

from core.db.write_v3.errors import WriteV3PlanningError
from core.db.write_v3.models import WritePlan, WriteRequest


def plan_write(engine: sa.Engine, request: WriteRequest) -> WritePlan:
    inspector = sa.inspect(engine)
    target = request.target
    table_exists = inspector.has_table(target.table_name, schema=target.schema_name)

    if not table_exists:
        full_name = f"{target.schema_name}.{target.table_name}" if target.schema_name else target.table_name
        raise WriteV3PlanningError(
            f"Target table '{full_name}' does not exist. write_v3 writes only to existing tables."
        )

    return WritePlan(
        dialect=engine.dialect.name.lower(),
        mode=request.mode,
        table_exists=table_exists,
        target=target,
        use_staging=request.mode in {"truncate", "upsert"},
        upsert_key=request.upsert.key_column if request.upsert else None,
    )
