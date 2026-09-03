import re
from datetime import datetime
from dataclasses import dataclass, fields
from typing import Any, List, Tuple, Union, get_args, get_origin, dataclass_transform, Type
from uuid import UUID

from core.hashing import get_hash

try:  # pragma: no cover - Python < 3.10 does not expose UnionType
    from types import UnionType
except ImportError:  # pragma: no cover
    UnionType = None

AllowedTypes = Union[str, int, float, bool, None, datetime, UUID, Tuple[str, ...], tuple[str, ...]]
ALLOWED_TYPES = get_args(AllowedTypes)
_PRIMITIVE_TYPES = (str, int, float, bool)


def is_allowed_type(tp: Any) -> bool:
    if tp in ALLOWED_TYPES:
        return True

    origin = get_origin(tp)
    args = get_args(tp)

    if origin is None:
        return False

    if origin is Union or (UnionType is not None and origin is UnionType):
        return all(is_allowed_type(arg) for arg in args)

    return False


def camel_to_snake(name: str) -> str:
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


class IndexKeyMeta(type):
    def __new__(cls, name, bases, namespace, **kwargs):
        processing = namespace.pop("_index_key_processing", False)
        annotations = namespace.get("__annotations__", {})

        if not processing:
            for field_name, field_type in annotations.items():
                if not is_allowed_type(field_type):
                    raise TypeError(
                        f"{name}.{field_name}: type {field_type!r} is not allowed for index keys"
                    )

        new_cls = super().__new__(cls, name, bases, namespace, **kwargs)

        if processing:
            return new_cls

        if annotations:
            setattr(new_cls, "_index_key_processing", True)
            new_cls = dataclass(frozen=True, slots=True)(new_cls)
            if hasattr(new_cls, "_index_key_processing"):
                delattr(new_cls, "_index_key_processing")

        return new_cls


@dataclass_transform(frozen_default=True, field_specifiers=())
class IndexKeyBase(metaclass=IndexKeyMeta):
    """
    Базовый класс для иерархических ключей индекса.
    """

    def to_segments(self, *, ensure_full: bool = False) -> List[AllowedTypes]:
        names = [f.name for f in fields(self) if f.init]
        segments: List[AllowedTypes] = []
        seen_none = False

        for name in names:
            value = getattr(self, name)
            if value is None:
                if ensure_full:
                    raise ValueError(f"Field '{name}' is None but full key required")
                seen_none = True
                continue

            if seen_none:
                raise ValueError(f"Field '{name}' set after None (gapped prefix)")

            segments.append(value)

        if not segments:
            raise ValueError("At least the first field must be provided")

        return [camel_to_snake(self.__class__.__name__)] + segments

    def to_string_segments(self, *, ensure_full: bool = False) -> List[str]:
        stringified: List[str] = []
        for segment in self.to_segments(ensure_full=ensure_full):
            if isinstance(segment, _PRIMITIVE_TYPES):
                stringified.append(str(segment))
            else:
                stringified.append(get_hash(segment).hex())
        return stringified

    def to_str(self, *, sep: str, ensure_full: bool = False) -> str:
        return sep.join(self.to_string_segments(ensure_full=ensure_full))


def index_key_from_str(key_cls: Type[IndexKeyBase], key_str: str, *, sep: str) -> IndexKeyBase:
    """
    Создает экземпляр IndexKey из строки.

    Args:
        key_cls: Класс IndexKey (например, PDFIndexKey)
        key_str: Строка вида 'val1{sep}val2{sep}val3'
        sep: Разделитель, используемый в строке

    Returns:
        Экземпляр класса с заполненными полями
    """
    segments = key_str.split(sep)

    key_name = segments.pop(0)

    if camel_to_snake(key_cls.__name__) != key_name:
        raise ValueError(
            f"Key class and key name not match: {key_name} != {camel_to_snake(key_cls.__name__)}"
        )

    # Получаем поля dataclass
    field_names = [f.name for f in fields(key_cls) if f.init]

    if len(segments) > len(field_names):
        raise ValueError(
            f"Too many segments in key string: got {len(segments)}, "
            f"expected at most {len(field_names)}"
        )

    # Создаем аргументы для конструктора
    kwargs = {}
    for i, (field_name, segment) in enumerate(zip(field_names, segments)):
        kwargs[field_name] = _parse_segment(segment, str)

    # Заполняем оставшиеся поля None
    for field_name in field_names[len(segments):]:
        kwargs[field_name] = None

    return key_cls(**kwargs)


def _parse_segment(segment: str, field_type: Any) -> Any:
    """
    Парсит сегмент строки в значение соответствующего типа.
    """
    # Если тип - Union, берем первый не-None тип
    origin = get_origin(field_type)
    if origin is Union or (UnionType is not None and origin is UnionType):
        # Ищем первый подходящий тип (исключая None)
        for arg in get_args(field_type):
            if arg is type(None):
                continue
            try:
                return _parse_segment(segment, arg)
            except (ValueError, TypeError):
                continue
        raise ValueError(f"Cannot parse '{segment}' as any of {get_args(field_type)}")

    # Базовые типы
    if field_type is str:
        return segment
    elif field_type is int:
        return int(segment)
    elif field_type is float:
        return float(segment)
    elif field_type is bool:
        return segment.lower() in ('true', '1', 'yes', 'on')
    elif field_type is type(None):
        return None
    elif field_type is UUID:
        return UUID(segment)
    else:
        # Для других типов возвращаем как строку
        return segment

__all__ = ["AllowedTypes", "IndexKeyBase", "is_allowed_type", "index_key_from_str"]
