from __future__ import annotations

from typing import Any, Dict, Generic, Iterable, Optional, Tuple, TypeVar, Union, cast

from core.storage.base import Storage

from .base_key import IndexKeyBase

K = TypeVar("K", bound=IndexKeyBase)
V = TypeVar("V")


class ItemSet(Generic[V], set[V]):
    """Набор значений с дополнительными утилитами."""

    def first(self) -> Optional[V]:
        return next(iter(self), None)

    def all(self) -> list[V]:
        return list(self)

    def order_by(self, *keys: str, reverse: bool = False) -> "ItemSet[V]":
        return ItemSet(
            sorted(self, key=lambda item: tuple(getattr(item, k) for k in keys), reverse=reverse)
        )


class _TrieNode:
    __slots__ = ("children", "store_keys")

    def __init__(self) -> None:
        self.children: Dict[str, "_TrieNode"] = {}
        self.store_keys: set[str] = set()


def _ensure_index_key(value: IndexKeyBase) -> IndexKeyBase:
    if not isinstance(value, IndexKeyBase):
        raise TypeError("Index key must inherit from IndexKeyBase")
    return value


class IndexStorage(Generic[K, V]):
    """
    Префиксный индекс, работающий с ключами-датаклассами (IndexKeyBase),
    но хранящий данные в сторе под строковыми ключами.
    """

    _STORE_KEY_SEPARATOR = "\x1F"

    def __init__(self, store: Storage[V], *, separator: str = ":") -> None:
        if not separator:
            raise ValueError("separator must be a non-empty string")

        self._separator = separator
        self._store: Storage[V] = store
        self._root: _TrieNode = _TrieNode()
        self._by_store_key: Dict[str, K] = {}

    @property
    def separator(self) -> str:
        return self._separator

    @staticmethod
    def _make_store_key(path: Tuple[str, ...]) -> str:
        return IndexStorage._STORE_KEY_SEPARATOR.join(path)

    def _key_to_path(self, index_key: IndexKeyBase, *, ensure_full: bool = False) -> Tuple[str, ...]:
        key = _ensure_index_key(index_key)
        segments = key.to_string_segments(ensure_full=ensure_full)
        if any(segment == "" for segment in segments):
            raise ValueError("Index key contains empty segment")
        return tuple(segments)

    async def _walk_create(self, path: Tuple[str, ...]) -> list[_TrieNode]:
        node = self._root
        stack: list[_TrieNode] = []
        for segment in path:
            child = node.children.get(segment)
            if child is None:
                child = _TrieNode()
                node.children[segment] = child
            node = child
            stack.append(node)
        return stack

    async def _walk_exact(self, path: Tuple[str, ...]) -> Optional[_TrieNode]:
        node = self._root
        for segment in path:
            node = node.children.get(segment)
            if node is None:
                return None
        return node

    async def _walk_exact_with_stack(
        self, path: Tuple[str, ...]
    ) -> Tuple[Optional[_TrieNode], list[tuple[Optional[_TrieNode], str, _TrieNode]]]:
        node = self._root
        stack: list[tuple[Optional[_TrieNode], str, _TrieNode]] = []
        parent: Optional[_TrieNode] = None

        for segment in path:
            child = node.children.get(segment)
            if child is None:
                return None, stack
            stack.append((parent, segment, child))
            parent = child
            node = child

        return node, stack

    def _is_exact_key(self, path: Tuple[str, ...]) -> bool:
        return self._make_store_key(path) in self._by_store_key

    # ---------- публичный API ----------

    async def put(self, index_key: K, value: V) -> str:
        """
        Добавляет объект в индекс под полным ключом и сохраняет значение в store.
        Возвращает store_key.
        """
        path = self._key_to_path(index_key, ensure_full=True)
        store_key = self._make_store_key(path)

        stack = await self._walk_create(path)
        for node in stack:
            node.store_keys.add(store_key)

        await self._store.put(store_key, value)
        self._by_store_key[store_key] = index_key
        return store_key

    async def remove(self, index_key: K) -> list[str]:
        """
        Удаляет все значения по префиксу.
        Возвращает список удалённых store_key.
        """
        path = self._key_to_path(index_key, ensure_full=False)
        node, stack = await self._walk_exact_with_stack(path)
        if node is None:
            return []

        keys_to_remove = list(node.store_keys)

        for store_key in keys_to_remove:
            await self._store.remove(store_key)
            self._by_store_key.pop(store_key, None)

        for _, _, current in stack:
            current.store_keys.difference_update(keys_to_remove)

        for parent, edge_value, child in reversed(stack):
            if child.store_keys or child.children:
                continue
            if parent is None:
                self._root.children.pop(edge_value, None)
            else:
                parent.children.pop(edge_value, None)

        return keys_to_remove

    async def get_by_store_key(self, store_key: str) -> Optional[V]:
        return await self._store.get(store_key)

    def store_key_to_index_key(self, store_key: str) -> Optional[str]:
        key = self._by_store_key.get(store_key)
        if key is None:
            return None
        return key.to_str(sep=self._separator, ensure_full=True)

    async def query_pairs(self, index_key: K) -> list[tuple[str, K, V]]:
        """
        Возвращает список (store_key, index_key, value) по заданному префиксу.
        """
        path = self._key_to_path(index_key, ensure_full=False)
        node = await self._walk_exact(path)
        if node is None:
            return []

        result: list[tuple[str, K, V]] = []
        for store_key in node.store_keys:
            value = await self._store.get(store_key)
            if value is None:
                continue
            stored_key = self._by_store_key.get(store_key)
            if stored_key is None:
                continue
            result.append((store_key, cast(K, stored_key), value))
        return result

    async def query(self, index_key: K) -> ItemSet[V]:
        """
        Возвращает множество значений под префиксом.
        """
        path = self._key_to_path(index_key, ensure_full=False)
        node = await self._walk_exact(path)
        if node is None:
            return ItemSet()

        result = ItemSet[V]()
        for store_key in node.store_keys:
            value = await self._store.get(store_key)
            if value is not None:
                result.add(value)
        return result

    async def query_grouped(self, index_key: K) -> Union[ItemSet[V], Dict[str, Any]]:
        """
        Возвращает подструктуру, начиная с указанного префикса.
        Если путь указывает на листья — возвращает ItemSet[V], иначе словарь сегментов -> поддерево.
        """
        path = self._key_to_path(index_key, ensure_full=False)
        node = await self._walk_exact(path)

        if node is None:
            if self._is_exact_key(path):
                return ItemSet()
            return {}

        if self._is_exact_key(path):
            leaf_values = ItemSet[V]()
            for store_key in node.store_keys:
                value = await self._store.get(store_key)
                if value is not None:
                    leaf_values.add(value)
            return leaf_values

        async def _build_subtree(current: _TrieNode) -> Any:
            if not current.children:
                leaf_values = ItemSet[V]()
                for store_key in current.store_keys:
                    value = await self._store.get(store_key)
                    if value is not None:
                        leaf_values.add(value)
                return leaf_values

            subtree: Dict[str, Any] = {}
            for segment, child in current.children.items():
                subtree[segment] = await _build_subtree(child)
            return subtree

        return await _build_subtree(node)

    async def contains(self, index_key: K) -> bool:
        """
        Проверяет наличие значений под префиксом.
        """
        path = self._key_to_path(index_key, ensure_full=False)
        node = await self._walk_exact(path)
        return bool(node and node.store_keys)

    async def keys(self) -> list[tuple[str, K]]:
        """Возвращает все пары (store_key, index_key), известные индексу."""
        return list(self._by_store_key.items())

    async def clear(self) -> None:
        """Очищает индекс и базовое хранилище."""
        self._root = _TrieNode()
        self._by_store_key.clear()
        await self._store.clear()

    async def reindex(self, pairs: Iterable[tuple[K, V]], *, clear_first: bool = True) -> None:
        """
        Перестраивает индекс из произвольной последовательности пар (ключ, значение).
        """
        if clear_first:
            await self.clear()
        for index_key, value in pairs:
            await self.put(index_key, value)

    def __dask_tokenize__(self) -> tuple[str]:
        return (self._separator,)


__all__ = ["IndexStorage", "ItemSet"]
