from fastapi import APIRouter, Response

from src.logger import get_logs_list


router = APIRouter(
    prefix="/logs",
    tags=["Logs"]
)


@router.get("/", summary="Получить отформатированные логи")
async def get_logs() -> Response:
    """
    Возвращает логи в виде одной строки.
    """
    # Используем Response для корректной отправки текста
    return Response(content="\n".join(get_logs_list()), media_type="text/plain")
