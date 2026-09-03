import importlib
import pickle
from io import BytesIO
from typing import Annotated, Any, Optional, Type, Union, get_args, get_origin

try:  # Python <3.10 compatibility (defensive)
    from types import UnionType
except ImportError:  # pragma: no cover
    UnionType = None  # type: ignore[assignment]

import pydantic as pyd

from .protocol import CacheEngine


def _unwrap_annotation(annotation: Any) -> Any:
    """
    Extract the underlying annotation, unwrapping Annotated layers if necessary.
    """
    ann = annotation
    while True:
        origin = get_origin(ann)
        if origin is Annotated:
            args = get_args(ann)
            if args:
                ann = args[0]
                continue
        return ann


def _is_union_type(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin is Union:
        return True
    if UnionType is not None and origin is UnionType:
        return True
    return False


def _extract_union_annotation(field: Any) -> Any:
    annotation = getattr(field, "annotation", None)
    annotation = _unwrap_annotation(annotation)
    if annotation is not None and _is_union_type(annotation):
        return annotation

    sa_type = getattr(field, "sa_type", None)
    pydantic_type = getattr(sa_type, "pydantic_type", None)
    pydantic_type = _unwrap_annotation(pydantic_type)
    if pydantic_type is not None and _is_union_type(pydantic_type):
        return pydantic_type

    return None


def _get_union_annotation(field: Any, model_cls: Type[pyd.BaseModel], field_name: str) -> Any:
    union_annotation = _extract_union_annotation(field)
    if union_annotation is not None:
        return union_annotation

    for base in model_cls.__mro__[1:]:
        base_fields = getattr(base, "model_fields", None)
        if not base_fields or field_name not in base_fields:
            continue
        union_annotation = _extract_union_annotation(base_fields[field_name])
        if union_annotation is not None:
            return union_annotation

    return None


def _collect_union_metadata(
    model: pyd.BaseModel,
    *,
    path: tuple[str, ...] = (),
    stack: tuple[int, ...] = (),
) -> list[dict[str, Any]]:
    model_id = id(model)
    if model_id in stack:
        return []

    next_stack = stack + (model_id,)
    entries: list[dict[str, Any]] = []

    model_fields = model.__class__.model_fields

    for name, field in model_fields.items():
        value = getattr(model, name, None)
        if value is None:
            continue

        union_annotation = _get_union_annotation(field, model.__class__, name)
        current_path = path + (name,)

        if union_annotation is not None and isinstance(value, pyd.BaseModel):
            entries.append(
                {
                    "path": list(current_path),
                    "model_module": value.__class__.__module__,
                    "model_name": value.__class__.__name__,
                    "model_qualname": value.__class__.__qualname__,
                }
            )
            entries.extend(_collect_union_metadata(value, path=current_path, stack=next_stack))
        elif isinstance(value, pyd.BaseModel):
            entries.extend(_collect_union_metadata(value, path=current_path, stack=next_stack))

    return entries


def _restore_union_models(payload: Any, union_meta: Optional[list[dict[str, Any]]]) -> None:
    if not union_meta or not isinstance(payload, dict):
        return

    sorted_meta = sorted(union_meta, key=lambda entry: len(entry.get("path", ())), reverse=True)

    for entry in sorted_meta:
        path = entry.get("path")
        if not path:
            continue

        parent: Any = payload
        missing_parent = False
        for segment in path[:-1]:
            if not isinstance(parent, dict):
                missing_parent = True
                break
            parent = parent.get(segment)
            if parent is None:
                missing_parent = True
                break

        if missing_parent or parent is None or not isinstance(parent, dict):
            continue

        last_key = path[-1]
        raw_value = parent.get(last_key)
        if raw_value is None:
            continue

        if isinstance(raw_value, pyd.BaseModel):
            value_payload = raw_value.model_dump()
        else:
            value_payload = raw_value

        if not isinstance(value_payload, dict):
            continue

        model_identifier = entry.get("model_qualname") or entry.get("model_name")
        model_module = entry.get("model_module")
        if not model_identifier or not model_module:
            continue

        model_cls: Type[pyd.BaseModel] = _import_model(model_module, model_identifier)
        parent[last_key] = model_cls(**value_payload)


def _import_model(module_name: str, qualname: str) -> Type[pyd.BaseModel]:
    module = importlib.import_module(module_name)
    obj = module
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj  # type: ignore[return-value]


class PydanticModelCacheEngine(CacheEngine[pyd.BaseModel]):
    """
    Универсальный движок для Pydantic.
    """
    name = "pydantic-model"

    def can_handle(self, obj: Any) -> bool:
        return isinstance(obj, pyd.BaseModel)

    def dump(self, obj: pyd.BaseModel) -> tuple[bytes, Optional[dict]]:
        if not isinstance(obj, pyd.BaseModel):
            raise TypeError(f"{self.name} can handle only pyd.Pydantic, got: {type(obj)}")

        meta = {
            "model_name": obj.__class__.__name__,
            "model_qualname": obj.__class__.__qualname__,
            "model_module": obj.__class__.__module__,
        }
        union_meta = _collect_union_metadata(obj)
        if union_meta:
            meta["union_models"] = union_meta

        buf = BytesIO()
        pickle.dump(obj.model_dump(), buf)
        return buf.getvalue(), meta

    def load(
        self,
        data: bytes,
        *,
        meta: Optional[dict] = None
    ) -> pyd.BaseModel:
        if not meta:
            raise ValueError("Meta information is required to restore Pydantic model")

        model_identifier = meta.get("model_qualname") or meta["model_name"]
        model_cls: Type[pyd.BaseModel] = _import_model(meta["model_module"], model_identifier)

        buf = BytesIO(data)
        obj_dict = pickle.load(buf)

        if isinstance(obj_dict, dict):
            _restore_union_models(obj_dict, meta.get("union_models"))

        return model_cls(**obj_dict)
