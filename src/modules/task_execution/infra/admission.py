import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from .db_models.admission import TaskAdmissionControlRecord


async def task_admission_state(
    session: AsyncSession, *, lock: bool = False
) -> tuple[str | None, bool]:
    # Production uses PostgreSQL. SQLite is the in-process unit-test backend.
    if session.get_bind().dialect.name == "sqlite":
        return None, False
    admission = TaskAdmissionControlRecord
    query = sa.select(admission.operation_id, admission.frozen).where(admission.singleton == 1)
    if lock:
        # Shared across submissions; the maintenance executor takes the exclusive row lock.
        query = query.with_for_update(read=True)
    operation_id, frozen = (await session.execute(query)).one()
    return operation_id, frozen
