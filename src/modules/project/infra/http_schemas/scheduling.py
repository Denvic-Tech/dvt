from src.schemas.http.common import CommonResponse


class ScheduleResponse(CommonResponse):
    project_id: str
