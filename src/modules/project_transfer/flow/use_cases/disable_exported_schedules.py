from __future__ import annotations

from collections.abc import Sequence

from ...domain.gateways import ScheduleGateway
from ...domain.types import TransferWarningCode
from ...domain.value_objects import TransferActor, TransferWarning


class DisableExportedSchedulesUseCase:
    """Turn off schedules of exported projects once the archive has been produced."""

    def __init__(self, *, schedules: ScheduleGateway) -> None:
        self._schedules = schedules

    async def execute(
        self,
        project_ids: Sequence[str],
        *,
        actor: TransferActor,
    ) -> list[TransferWarning]:
        if not project_ids:
            return []
        if not actor.can_manage_schedules:
            return [
                TransferWarning(
                    code=TransferWarningCode.SCHEDULE_FORBIDDEN,
                    message="Only administrators may disable schedules; schedules were left unchanged",
                )
            ]
        warnings: list[TransferWarning] = []
        for project_id in project_ids:
            try:
                await self._schedules.disable(project_id)
            except Exception as exc:
                warnings.append(
                    TransferWarning(
                        code=TransferWarningCode.SCHEDULE_DISABLE_FAILED,
                        message=f"Schedule of project '{project_id}' could not be disabled: {exc}",
                        details={"project_id": project_id},
                    )
                )
        return warnings
