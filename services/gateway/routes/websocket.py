"""
Роутер для обработки WebSocket соединений.
"""
import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from services.gateway.deps import WebSocketManager, get_websocket_manager

from src.logger import logger
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.event import PingEvent

WebsocketManagerDep = Annotated[WebSocketManager, Depends(get_websocket_manager)]


router = APIRouter(
    tags=["WebSocket"],
)


@router.websocket("/ws")
async def websocket_endpoint(
        websocket: WebSocket,
        project_id: str,
        user: UserAccessOnly,
        websocket_manager: WebsocketManagerDep,
):
    """Основной WebSocket эндпоинт."""

    await websocket_manager.connect(
        websocket=websocket,
        user_id=user.id,
        project_id=project_id
    )

    try:
        pass
        # TODO: Отправить текущий выполняемый узел, если этот клиент выполнял задачу
        # Логика получения last_task_id и last_node_id для клиента потребует
        # доработки в QueueManager или TaskExecutor для отслеживания связи user_id <-> task_id.
        # last_task_id = queue_manager.get_last_task_id_for_client(user_id)
        # if last_task_id and executor.is_running(last_task_id):
        #    last_node = executor.get_last_node_id(last_task_id)
        #    if last_node:
        #         executing_msg = ExecutingMessage(data={"node": last_node, "task_id": last_task_id})
        #         await manager.send_personal_message(executing_msg, user_id)

    except Exception as e:
        logger.error(f"Error sending initial status to client {user.id}: {e}")

    try:
        # Цикл ожидания сообщений от клиента (если нужно) и поддержания соединения
        while True:
            # В текущей реализации клиент не отправляет сообщений серверу через WS,
            # поэтому этот цикл в основном для поддержания соединения.
            try:
                # Ждем pong или любое другое сообщение от клиента с таймаутом
                await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                # Если получили сообщение, можно его обработать (сейчас игнорируем)
                # logger.debug(f"Received keep-alive message from {user_id}")
            except TimeoutError:
                # Таймаут - отправляем ping для проверки
                try:
                    await websocket_manager.send_personal_message(
                        message=PingEvent(),
                        user_id=user.id,
                        project_id=project_id
                    )
                    # await websocket.ping()
                    # logger.debug(f"Sent ping to client {user_id}")
                except (WebSocketDisconnect, ConnectionResetError, RuntimeError):
                    logger.warning(f"Client {user.id} disconnected during ping.")
                    break
            except WebSocketDisconnect:
                logger.info(f"Client {user.id} disconnected.")
                break
            except Exception as e:
                logger.error(f"WebSocket keep-alive error for {user.id}: {e}")
                break  # Ошибка, отключаем

    except WebSocketDisconnect:
        logger.info(f"Client {user.id} disconnected gracefully.")
    except Exception as e:
        # Логируем ошибку, если она произошла не из-за отключения
        if not isinstance(e, (WebSocketDisconnect, ConnectionResetError)):
            logger.error(f"WebSocket error for client {user.id}: {e}")
    finally:
        # Гарантированно удаляем соединение при выходе
        websocket_manager.disconnect(user.id, project_id)
        logger.info(f"WebSocket connection closed for client {user.id}")
