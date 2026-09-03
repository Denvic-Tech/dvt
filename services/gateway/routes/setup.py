from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, status

from src import setup
from src.db import AsyncSession
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.setup import SetupConflictError, SetupValidationError
from src.setup.dsl import SetupStatus, SetupStepSubmitRequest

router = r = APIRouter(prefix="/setup", tags=["Setup"])


def _map_setup_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SetupConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, SetupValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    raise exc


def _build_submit_handler(
    step_code: str,
) -> Callable[[SetupStepSubmitRequest, AsyncSession], Awaitable[SetupStatus]]:
    async def submit_setup_step(
        request: SetupStepSubmitRequest,
        session: AsyncSessionDepends,
    ) -> SetupStatus:
        try:
            return await setup.submit_setup_step(
                session,
                step_code=step_code,
                values=request.values,
            )
        except (SetupConflictError, SetupValidationError) as exc:
            raise _map_setup_error(exc) from exc

    submit_setup_step.__name__ = f"submit_setup_step_{step_code}"
    return submit_setup_step


@r.get("/status", response_model=SetupStatus)
async def get_setup_status(
    session: AsyncSessionDepends,
) -> SetupStatus:
    return await setup.get_setup_status(session)


for step_cls in setup.get_all_setup_steps():
    router.add_api_route(
        f"/{step_cls.CODE}",
        _build_submit_handler(step_cls.CODE),
        methods=["POST"],
        response_model=SetupStatus,
        status_code=status.HTTP_200_OK,
        summary=f"Submit setup step '{step_cls.TITLE}'",
    )
