from abc import ABC
from typing import Optional, TypeVar, Generic, Callable

T = TypeVar('T')
OnItemRemoveCallback = Callable[[str], None]


class Storage(ABC, Generic[T]):
    """
    Протокол (интерфейс) для хранилищ кеша.
    Определяет базовые методы, которые должно реализовывать любое хранилище.
    """

    def __init__(
            self,
            *,
            on_item_remove: Optional[OnItemRemoveCallback] = None
    ):
        self._handle_item_removal = on_item_remove or (lambda k: None)

    async def get(self, key: str) -> Optional[T]:
        """Получает сериализованные данные из хранилища по ключу."""
        ...

    async def put(self, key: str, value: T) -> None:
        """Сохраняет сериализованные данные в хранилище."""
        ...

    async def remove(self, key: str, *keys: str) -> None:
        """Удаляет данные из хранилища по ключу."""
        ...

    async def has(self, key: str) -> bool:
        """Проверяет наличие данных в хранилище по ключу."""
        ...

    async def clear(self) -> None:
        """Очищает все хранилище."""
        ...

    async def keys(self) -> list[str]:
        """Возвращает список всех ключей в хранилище."""
        ...

    async def values(self) -> list[T]:
        """Возвращает список всех значений в хранилище."""
        ...

    async def items(self) -> list[tuple[str, T]]:
        """Возвращает список всех (ключ, значение) в хранилище."""
        ...

    async def dict(self) -> dict[str, T]:
        """Возвращает все хранилище в виде словаря."""
        ...
