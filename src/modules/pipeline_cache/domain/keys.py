import re
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Union, get_args, get_origin, dataclass_transform, Type
from uuid import UUID

from core.hashing import get_hash

from .exceptions import InvalidIndexKeyError

try:
    from types import UnionType
except ImportError:  # pragma: no cover
    UnionType = None

AllowedTypes = Union[str, int, float, bool, None, datetime, UUID, tuple[str, ...]]
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
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class IndexKeyMeta(type):
    def __new__(cls, name, bases, namespace, **kwargs):
        processing = namespace.pop("_index_key_processing", False)
        annotations = namespace.get("__annotations__", {})

        if not processing:
            for field_name, field_type in annotations.items():
                if not is_allowed_type(field_type):
                    raise TypeError(f"{name}.{field_name}: type {field_type!r} is not allowed for index keys")

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
    def to_segments(self, *, ensure_full: bool = False) -> list[AllowedTypes]:
        names = [field.name for field in fields(self) if field.init]
        segments: list[AllowedTypes] = []
        seen_none = False

        for name in names:
            value = getattr(self, name)
            if value is None:
                if ensure_full:
                    raise InvalidIndexKeyError(f"Field '{name}' is None but full key required")
                seen_none = True
                continue
            if seen_none:
                raise InvalidIndexKeyError(f"Field '{name}' set after None (gapped prefix)")
            segments.append(value)

        if not segments:
            raise InvalidIndexKeyError("At least the first field must be provided")

        return [camel_to_snake(self.__class__.__name__)] + segments

    def to_string_segments(self, *, ensure_full: bool = False) -> list[str]:
        stringified: list[str] = []
        for segment in self.to_segments(ensure_full=ensure_full):
            if isinstance(segment, _PRIMITIVE_TYPES):
                stringified.append(str(segment))
            else:
                stringified.append(get_hash(segment).hex())
        return stringified

    def to_str(self, *, sep: str, ensure_full: bool = False) -> str:
        return sep.join(self.to_string_segments(ensure_full=ensure_full))


def index_key_from_str(key_cls: Type[IndexKeyBase], key_str: str, *, sep: str) -> IndexKeyBase:
    segments = key_str.split(sep)
    key_name = segments.pop(0)

    expected_key_name = camel_to_snake(key_cls.__name__)
    if expected_key_name != key_name:
        raise InvalidIndexKeyError(f"Key class and key name not match: {key_name} != {expected_key_name}")

    field_names = [field.name for field in fields(key_cls) if field.init]
    if len(segments) > len(field_names):
        raise InvalidIndexKeyError(
            f"Too many segments in key string: got {len(segments)}, expected at most {len(field_names)}"
        )

    kwargs: dict[str, Any] = {}
    field_types = {field.name: field.type for field in fields(key_cls) if field.init}
    for field_name, segment in zip(field_names, segments):
        kwargs[field_name] = _parse_segment(segment, field_types[field_name])
    for field_name in field_names[len(segments):]:
        kwargs[field_name] = None
    return key_cls(**kwargs)


def _parse_segment(segment: str, field_type: Any) -> Any:
    origin = get_origin(field_type)
    if origin is Union or (UnionType is not None and origin is UnionType):
        for arg in get_args(field_type):
            if arg is type(None):
                continue
            try:
                return _parse_segment(segment, arg)
            except (ValueError, TypeError):
                continue
        raise InvalidIndexKeyError(f"Cannot parse '{segment}' as any of {get_args(field_type)}")

    if field_type is str:
        return segment
    if field_type is int:
        return int(segment)
    if field_type is float:
        return float(segment)
    if field_type is bool:
        return segment.lower() in ("true", "1", "yes", "on")
    if field_type is type(None):
        return None
    if field_type is UUID:
        return UUID(segment)
    return segment


class CommonNodeKey(IndexKeyBase):
    project_id: str | None = None
    node_id: str | None = None


class CommonOutputKey(CommonNodeKey):
    output_name: str | None = None


class MetaKey(CommonNodeKey):
    meta_key_id: str | None = None


class DDFMetaKey(CommonOutputKey):
    pass


class PDFKey(CommonOutputKey):
    part_no: int | None = None


class JSONKey(CommonOutputKey):
    pass
