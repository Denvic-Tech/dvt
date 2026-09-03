from dataclasses import dataclass

from cachetools import TTLCache
from contracts.src.ws_forward.v1 import forward_pb2, forward_pb2_grpc
from loguru import logger
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.deps import WebSocketManager

from src.db.session import get_async_session_acm
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord
from src.schemas.event import Event
from src.utils.user_roles import user_has_admin_access, user_has_global_access


@dataclass(frozen=True)
class CachedUserInfo:
    has_admin_access: bool
    has_global_access: bool
    owner_id: str
    organization_id: str
    project_organization_id: str


project2user: TTLCache[tuple[str, str], CachedUserInfo] = TTLCache(maxsize=100, ttl=60 * 10)


WS_EVENT_ADAPTER = TypeAdapter(Event)


def _parse_ws_message(payload_json: str):
    return WS_EVENT_ADAPTER.validate_json(payload_json)


async def _check_project_belongs_to_user(
        session: AsyncSession,
        project_id: str,
        user_id: str
) -> bool:
    key = (project_id, user_id)

    cached = project2user.get(key)
    if cached is not None:
        if cached.has_global_access:
            return True
        if cached.has_admin_access:
            return cached.organization_id == cached.project_organization_id

        return cached.owner_id == user_id and cached.organization_id == cached.project_organization_id

    project = await session.get(ProjectRecord, project_id)
    if project is None:
        return False

    user = await session.get(UserRecord, user_id)
    if user is None:
        return False

    has_admin_access = user_has_admin_access(user)
    has_global_access = user_has_global_access(user)
    owner_id = project.user_id

    project2user[key] = CachedUserInfo(
        has_admin_access=has_admin_access,
        has_global_access=has_global_access,
        owner_id=owner_id,
        organization_id=user.organization_id,
        project_organization_id=project.organization_id,
    )

    if has_global_access:
        return True
    if has_admin_access:
        return project.organization_id == user.organization_id

    return owner_id == user_id and project.organization_id == user.organization_id


class ForwardWSServicer(forward_pb2_grpc.ForwardWSServicer):
    def __init__(self, ws_manager: WebSocketManager):
        self.ws_manager = ws_manager

    async def ForwardStream(self, request_iterator, context):
        async with get_async_session_acm() as session:
            logger.info(f"ForwardStream started (peer={context.peer()})")
            try:
                async for req in request_iterator:
                    if not await _check_project_belongs_to_user(session, req.project_id, req.user_id):
                        logger.warning(
                            f"ForwardStream: project {req.project_id} not found for user {req.user_id}"
                        )
                        continue
                    try:
                        ws_msg = _parse_ws_message(req.payload_json)
                    except Exception as e:
                        logger.error(f"ForwardStream: failed to parse Event JSON: {e}")
                        continue

                    try:
                        self.ws_manager.send_sync(
                            message=ws_msg,
                            user_id=req.user_id,
                            project_id=req.project_id,
                        )
                    except Exception as e:
                        logger.exception(
                            "ForwardStream: failed to send message to websocket manager "
                            f"(user_id={req.user_id}, project_id={req.project_id}): {e}"
                        )
                        continue

            except Exception as e:
                logger.exception("ForwardStream crashed")
                return forward_pb2.ForwardAck(ok=False, error=str(e))

        return forward_pb2.ForwardAck(ok=True)

    async def ForwardUnary(self, request, context):
        async with get_async_session_acm() as session:
            if not await _check_project_belongs_to_user(session, request.project_id, request.user_id):
                return forward_pb2.ForwardAck(ok=False, error="project not found for user")
            try:
                ws_msg = _parse_ws_message(request.payload_json)
            except Exception as e:
                logger.error(f"ForwardUnary: failed to parse Event JSON: {e}")
                return forward_pb2.ForwardAck(ok=False, error="invalid websocket message json")

            try:
                self.ws_manager.send_sync(
                    message=ws_msg,
                    user_id=request.user_id,
                    project_id=request.project_id,
                )
            except Exception as e:
                logger.exception(
                    "ForwardUnary: failed to send message to websocket manager "
                    f"(user_id={request.user_id}, project_id={request.project_id}): {e}"
                )
                return forward_pb2.ForwardAck(ok=False, error="failed to forward message to websocket manager")
            return forward_pb2.ForwardAck(ok=True)
