"""
Менеджер WebSocket соединений для FastAPI.
"""
import asyncio
from typing import Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from src.logger import logger
from src.schemas.event import EventBase, Event


class WebSocketManager:
    """Управляет активными WebSocket соединениями."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        logger.info("WebSocketManager initialized.")

    def _capture_running_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        if self._loop is not None and not self._loop.is_closed():
            return self._loop
        try:
            self._loop = asyncio.get_running_loop()
            logger.info("WebSocketManager captured running event loop.")
            return self._loop
        except RuntimeError:
            return None

    @staticmethod
    def _build_connection_key(user_id: str, project_id: str) -> str:
        """Создает уникальный ключ для соединения на основе user_id и project_id."""
        return f"{user_id}:{project_id}"

    async def connect(
            self,
            websocket: WebSocket,
            user_id: str,
            project_id: str
    ):
        """Регистрирует новое WebSocket соединение."""
        await websocket.accept()
        connection_key = self._build_connection_key(user_id, project_id)
        self.active_connections[connection_key] = websocket
        logger.info(f"WebSocket client connected: ID={user_id}, ProjectID={project_id}")
        if self._capture_running_loop() is None:
            logger.error("Could not get running event loop in connect. send_sync might not work.")

    def disconnect(self, user_id: str, project_id: str):
        """Удаляет WebSocket соединение."""
        connection_key = self._build_connection_key(user_id, project_id)
        if connection_key in self.active_connections:
            del self.active_connections[connection_key]
            logger.info(f"WebSocket client disconnected: ID={user_id}, ProjectID={project_id}")

    async def _send_message(
            self,
            websocket: WebSocket,
            message: Event
    ):
        """Внутренний метод для отправки сообщения."""
        try:
            if isinstance(message, EventBase):
                await websocket.send_json(message.model_dump(mode='json'))
            else:
                raise TypeError(f"Unsupported message: ({type(message)}) {message}")

        except (WebSocketDisconnect, ConnectionResetError, RuntimeError) as e:
            # Эти ошибки означают, что соединение закрыто
            raise WebSocketDisconnect(reason=f"Connection closed or reset: {e}")

        except Exception as e:
            logger.error(f"Unexpected error sending WebSocket message: {e}")
            raise  # Перебрасываем другие ошибки

    async def send_personal_message(
            self,
            message: Event,
            user_id: str,
            project_id: str
    ):
        """Отправляет сообщение конкретному клиенту."""
        connection_key = self._build_connection_key(user_id, project_id)
        websocket = self.active_connections.get(connection_key)
        if websocket:
            try:
                await self._send_message(websocket, message)
            except WebSocketDisconnect as e:
                logger.warning(
                    f"Failed to send message to client ID={user_id}, ProjectID={project_id}: {e}. Disconnecting."
                )
                self.disconnect(user_id, project_id)
            except Exception:  # Ловим другие ошибки из _send_message
                # Ошибка уже залогирована в _send_message
                self.disconnect(user_id, project_id)  # Отключаем клиента при любой ошибке отправки

    async def broadcast(
            self,
            message: Event
    ):
        """Отправляет сообщение всем подключенным клиентам."""
        # Используем список user_id для безопасной итерации при возможном удалении
        connections = list(self.active_connections.keys())
        for connection in connections:
            user_id, project_id = connection.split(":", 1)
            websocket = self.active_connections.get(connection)  # Проверяем, не удалили ли его уже
            if websocket:
                try:
                    await self._send_message(websocket, message)
                except WebSocketDisconnect as e:
                    logger.warning(
                        f"Failed to broadcast message to client ID={user_id}, "
                        f"ProjectID={project_id}: {e}. Disconnecting."
                    )
                    self.disconnect(user_id, project_id)
                except Exception:
                    # Ошибка уже залогирована в _send_message
                    self.disconnect(user_id, project_id)

    def send_sync(
            self,
            message: Event,
            user_id: Optional[str] = None,
            project_id: Optional[str] = None
    ):
        """
        Безопасно отправляет сообщение из другого потока.
        Принимает готовую Pydantic модель EventBase.
        """
        loop = self._capture_running_loop()
        if loop is None:
            logger.warning("Event loop not available in WebSocketManager. Message dropped in send_sync.")
            return

        async def _send():
            if user_id and project_id:
                await self.send_personal_message(message=message, user_id=user_id, project_id=project_id)
            else:
                await self.broadcast(message)

        # Запускаем отправку в основном цикле asyncio
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), loop)
        else:
            logger.error("Event loop is not running. Cannot schedule message send.")
