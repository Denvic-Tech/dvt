from __future__ import annotations

from typing import Any, Protocol, Optional, TypeVar, runtime_checkable


T = TypeVar("T")


@runtime_checkable
class CacheEngine(Protocol[T]):
    """
    Контракт движка сериализации/десериализации для кеша.
    Движок сам отвечает за:
      - определение поддержки типа
      - сериализацию в bytes (+ опциональные meta)
      - десериализацию из bytes (+ meta)
      - вычисление стабильного hash для «смыслового равенства» объектов
    """

    # уникальное имя движка (ложится в payload)
    name: str

    def can_handle(self, obj: Any) -> bool:
        ...

    def dump(self, obj: T) -> tuple[bytes, Optional[dict]]:
        ...

    def load(
            self,
            data: bytes,
            *,
            meta: Optional[dict] = None
    ) -> T:
        ...
