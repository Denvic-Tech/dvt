from functools import lru_cache

from src.managers.websocket import WebSocketManager


@lru_cache(maxsize=1)
def get_websocket_manager() -> WebSocketManager:
    return WebSocketManager()
