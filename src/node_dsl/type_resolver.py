from __future__ import annotations

import inspect
import operator
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import reduce
from typing import get_args, get_origin, Optional, Type, ClassVar, ForwardRef

from typing import Any, Dict, List, Union, Tuple, Literal, Iterable, Set, FrozenSet

import kafka
import dask.dataframe as dd
import sqlalchemy as sa
from sqlalchemy.ext import asyncio as asa
from src.node_dsl.connection_types import (
    FTPConnectionRecord,
    FileConnectionRecord,
    KafkaConnectionRecord,
    SMBConnectionRecord,
    S3ConnectionRecord,
    SqlConnectionRecord,
)

from pydantic import BaseModel, TypeAdapter

from src.logger import logger
from src.modules.data_catalog.domain import TableSchema
from src.node_dsl.node_typing import IO, try_get_io_member


@dataclass
class ResolvedIOType:
    io_type: IO
    options: Optional[List[str]] = None
    is_list_type: bool = False
    is_literal_type: bool = False
    is_optional: bool = False
    schema: Optional[dict] = None


class TypeResolver:
    DEFAULT_TYPE_MAP: ClassVar[Dict[type, IO]] = {
        int: IO.INT,
        float: IO.FLOAT,
        str: IO.STRING,
        bool: IO.BOOLEAN,
        dict: IO.DICT,
        dd.DataFrame: IO.DATAFRAME,
        TableSchema: IO.TABLE_SCHEMA,
        dd.Series: IO.COLUMN,
        sa.Engine: IO.DB_CONNECTION,
        asa.AsyncEngine: IO.DB_CONNECTION,
        sa.Connection: IO.DB_CONNECTION,
        asa.AsyncConnection: IO.DB_CONNECTION,
        SqlConnectionRecord: IO.DB_CONNECTION,
        FileConnectionRecord: IO.FILE_CONNECTION,
        S3ConnectionRecord: IO.S3_CONNECTION,
        FTPConnectionRecord: IO.FTP_CONNECTION,
        SMBConnectionRecord: IO.SMB_CONNECTION,
        KafkaConnectionRecord: IO.KAFKA_CONNECTION,
        kafka.KafkaProducer: IO.KAFKA_CONNECTION,
        kafka.KafkaConsumer: IO.KAFKA_CONNECTION,
        datetime: IO.DATETIME,
        timedelta: IO.TIMEDELTA,
        Any: IO.ANY,
    }

    PRIMITIVE_IO_TYPES: ClassVar[frozenset[IO]] = frozenset({IO.STRING, IO.FLOAT, IO.INT, IO.BOOLEAN})
    PRIMITIVE_PY_TYPES: ClassVar[frozenset[Type]] = frozenset({str, float, int, bool})

    LIST_LIKE_ORIGINS: ClassVar[Set[Optional[type]]] = {
        list, List, tuple, Tuple, set, Set, frozenset, FrozenSet, Iterable
    }
    DICT_LIKE_ORIGINS: ClassVar[Set[Optional[type]]] = {dict, Dict}

    _SCHEMA_TYPE_TO_IO: ClassVar[Dict[str, IO]] = {
        "string": IO.STRING,
        "integer": IO.INT,
        "number": IO.FLOAT,
        "boolean": IO.BOOLEAN,
        "object": IO.DICT,  # plain dict (модели обрабатываем отдельно)
    }

    def __init__(self, custom_type_map: Optional[Dict[type, IO]] = None):
        self._type_map = self.DEFAULT_TYPE_MAP.copy()
        if custom_type_map:
            self._type_map.update(custom_type_map)
        self._type_name_map = {
            py_type.__name__: py_type
            for py_type in self._type_map
            if inspect.isclass(py_type)
        }

    # ---------- ПУБЛИЧНЫЙ ----------
    def resolve(self, py_type: Any) -> ResolvedIOType:
        origin = get_origin(py_type)
        args = get_args(py_type)

        # Прямой IO
        if isinstance(py_type, IO):
            return self._handle_direct_io(py_type)
        if isinstance(py_type, str):
            if (resolved_io := try_get_io_member(py_type)) is not None:
                return self._handle_direct_io(resolved_io)
            if (resolved_string_type := self._resolve_string_annotation(py_type)) is not None:
                return self.resolve(resolved_string_type)
        if isinstance(py_type, ForwardRef) and (
            resolved_io := try_get_io_member(py_type.__forward_arg__)
        ) is not None:
            return self._handle_direct_io(resolved_io)

        # >>> КРИТИЧЕСКОЕ: Union ДО TypeAdapter
        if self._is_union_annotation(py_type):
            non_none_args = [a for a in args if a is not type(None)]
            if non_none_args:
                resolved_non_none_args = [self.resolve(a) for a in non_none_args]
                sig0 = (
                    resolved_non_none_args[0].io_type,
                    resolved_non_none_args[0].is_list_type,
                    resolved_non_none_args[0].is_literal_type,
                )
                if all(
                    (r.io_type, r.is_list_type, r.is_literal_type) == sig0
                    and r.schema is None
                    for r in resolved_non_none_args
                ):
                    return ResolvedIOType(
                        io_type=resolved_non_none_args[0].io_type,
                        is_list_type=resolved_non_none_args[0].is_list_type,
                        is_literal_type=resolved_non_none_args[0].is_literal_type,
                        is_optional=type(None) in args,
                    )
            return self._handle_union(py_type, origin, args)

        # List/Tuple/Set ДО TypeAdapter
        if origin in self.LIST_LIKE_ORIGINS:
            return self._handle_list_like(py_type, origin, args)

        # Dict-подобные ДО TypeAdapter
        if origin in self.DICT_LIKE_ORIGINS:
            return self._handle_dict_like(py_type, origin, args)

        # Простое сопоставление
        if py_type in self._type_map:
            return ResolvedIOType(io_type=self._type_map[py_type])

        # Одиночная pydantic-модель
        if inspect.isclass(py_type) and issubclass(py_type, BaseModel):
            return self._handle_pydantic_model_via_type_adapter(py_type)

        # Универсально через TypeAdapter
        via_ta = self._resolve_with_type_adapter_simple(py_type)
        if via_ta is not None:
            return via_ta

        # <<< ПОСЛЕДНИЙ ШАНС: если вдруг это Union, но до сюда дошли — перехватить сейчас
        if self._is_union_annotation(py_type):
            return self._handle_union(py_type, origin, args)

        # Fallback
        if origin is Literal or py_type is Literal:
            return self._handle_literal(py_type, origin, args)

        return self._handle_direct_mapping_or_unknown(py_type, origin, args)

    # ---------- TypeAdapter-путь ----------
    def _resolve_with_type_adapter_simple(self, py_type: Any) -> Optional[ResolvedIOType]:
        try:
            root = TypeAdapter(py_type).json_schema()
        except Exception as e:
            logger.error(f"TypeAdapter schema generation failed for {py_type}: {e}")
            return None

        # ВАЖНО: если TA вернул anyOf/oneOf — это Union, обрабатываем не здесь
        if isinstance(root, dict) and ("anyOf" in root or "oneOf" in root):
            return None

        try:
            resolved = self._resolved_from_schema(root, root=root)
            return resolved
        except ValueError as e:
            raise
        except Exception as e:
            logger.error(f"TypeAdapter-based resolution fell back for {py_type}: {e}")
            return None

    def _resolved_from_schema(self, node: dict, *, root: dict) -> Optional[ResolvedIOType]:
        # $ref → pydantic модель
        if "$ref" in node:
            target = self._deref(root, node["$ref"]) or {}
            return ResolvedIOType(io_type=IO.SCHEMA, schema=target or {"type": "object"})

        # enum → Literal[str,...]
        if "enum" in node:
            enum_vals = node.get("enum") or []
            if all(isinstance(v, str) for v in enum_vals):
                return ResolvedIOType(io_type=IO.STRING, options=list(enum_vals), is_literal_type=True)

        t = node.get("type")

        # array → List[T]
        if t == "array":
            items = node.get("items")
            if not items:
                return ResolvedIOType(io_type=IO.ANY, is_list_type=True)
            inner = self._resolved_from_schema(items, root=root)
            if inner is None:
                return ResolvedIOType(io_type=IO.ANY, is_list_type=True)
            return ResolvedIOType(
                io_type=inner.io_type,
                options=inner.options,
                is_list_type=True,
                is_literal_type=inner.is_literal_type,
                is_optional=False,
                schema=inner.schema if inner.io_type is IO.SCHEMA else None
            )

        # object: отличаем dict от модели
        if t == "object":
            if "additionalProperties" in node and "properties" not in node and "$ref" not in node:
                return ResolvedIOType(io_type=IO.DICT)
            return ResolvedIOType(io_type=IO.SCHEMA, schema=node)

        # простые типы
        if t == "string":
            return ResolvedIOType(io_type=IO.STRING)
        if t == "integer":
            return ResolvedIOType(io_type=IO.INT)
        if t == "number":
            return ResolvedIOType(io_type=IO.FLOAT)
        if t == "boolean":
            return ResolvedIOType(io_type=IO.BOOLEAN)

        # (ВАЖНО) НЕ анализируем здесь Union — он перехвачен раньше в resolve()
        return None

    # ---------- Fallback-обработчики ----------
    def _handle_direct_io(self, io_enum_val: IO) -> ResolvedIOType:
        return ResolvedIOType(io_type=io_enum_val)

    def _handle_literal(self, py_type: Any, origin: Any, args: tuple[Any, ...]) -> ResolvedIOType:
        if not args:
            raise ValueError(f"Unsupported Literal type: must have arguments. Got: {py_type}")
        if any(not isinstance(arg, str) for arg in args):
            raise ValueError(f"Unsupported Literal type: arguments must be strings. Got: {py_type}")
        return ResolvedIOType(io_type=IO.STRING, options=list(args), is_literal_type=True)

    def _handle_union(self, py_type: Any, origin: Any, args: tuple[Any, ...]) -> ResolvedIOType:
        is_optional = type(None) in args
        non_none_args = [a for a in args if a is not type(None)]
        if not non_none_args:
            raise ValueError("Unsupported Union type: only NoneType")

        # Optional[T]
        if len(non_none_args) == 1:
            inner = self.resolve(non_none_args[0])
            inner.is_optional = is_optional
            return inner

        # Разрешаем каждую ножку Union отдельно
        resolved_args: List[ResolvedIOType] = [self.resolve(a) for a in non_none_args]

        # --- ИЗМЕНЕНИЕ НАЧАЛО ---
        # Упрощенная и исправленная логика для смешанных Union.
        # Если есть хотя бы одна схема или это просто смесь разных типов,
        # которую нужно представить схемой, мы генерируем 'oneOf'.
        has_schema = any(r.io_type is IO.SCHEMA for r in resolved_args)
        # Проверяем, есть ли несколько разных "сигнатур" типа (например, IO.STRING и IO.SCHEMA)
        is_complex_mix = len({(r.io_type, r.is_list_type) for r in resolved_args}) > 1

        if has_schema or is_complex_mix:
            # Для сложных union используем TypeAdapter над union целиком. Нельзя просто
            # вложить отдельно сгенерированные Pydantic-схемы в oneOf: их локальные
            # `$defs` останутся внутри веток, а ссылки `#/$defs/...` разрешаются от
            # корня документа и в результате получится невалидный JSON Schema.
            schema_type = reduce(operator.or_, non_none_args)
            try:
                union_schema = TypeAdapter(schema_type).json_schema()
                # Preserve the public NodeDefinition contract used before this
                # fix: complex unions are exposed as ``oneOf``. TypeAdapter
                # places shared ``$defs`` at the document root, which keeps
                # local refs valid; only the top-level union keyword is
                # normalized for backward compatibility.
                if "anyOf" in union_schema and "oneOf" not in union_schema:
                    union_schema["oneOf"] = union_schema.pop("anyOf")

                # Preserve the previous shape of NodeDefinition schemas: the
                # top-level union branches were inline objects, not bare refs.
                # Keep shared $defs at the root so refs nested inside an inlined
                # branch still resolve correctly.
                if isinstance(union_schema.get("oneOf"), list):
                    union_schema["oneOf"] = [
                        dict(self._deref(union_schema, branch["$ref"]))
                        if (
                            isinstance(branch, dict)
                            and set(branch) == {"$ref"}
                            and self._deref(union_schema, branch["$ref"])
                        )
                        else branch
                        for branch in union_schema["oneOf"]
                    ]
            except Exception as exc:
                logger.error(f"TypeAdapter union schema generation failed for {py_type}: {exc}")
                union_schema = {"oneOf": [self._io_to_schema(r) for r in resolved_args]}

            return ResolvedIOType(
                io_type=IO.SCHEMA,
                is_optional=is_optional,
                schema=union_schema,
            )
        # --- ИЗМЕНЕНИЕ КОНЕЦ ---

        # Одинаковая сигнатура (без моделей) → схлопываем
        # Этот блок теперь будет обрабатывать, например, Union[Literal["a"], Literal["b"]]
        sig0 = (resolved_args[0].io_type, resolved_args[0].is_list_type, resolved_args[0].is_literal_type)
        if all((r.io_type, r.is_list_type, r.is_literal_type) == sig0 for r in resolved_args):
            merged_options = None
            if resolved_args[0].is_literal_type:
                opts: Set[str] = set()
                for r in resolved_args:
                    if r.options:
                        opts.update(r.options)
                merged_options = sorted(opts)
            return ResolvedIOType(
                io_type=resolved_args[0].io_type,
                options=merged_options,
                is_list_type=resolved_args[0].is_list_type,
                is_literal_type=resolved_args[0].is_literal_type,
                is_optional=is_optional,
            )

        # Fallback на случай, если какая-то логика не покрыта выше (маловероятно)
        return ResolvedIOType(
            io_type=IO.ANY,
            is_optional=is_optional,
            schema={"oneOf": [self._io_to_schema(r) for r in resolved_args]},
        )

    def _handle_list_like(self, py_type: Any, origin: Any, args: tuple[Any, ...]) -> ResolvedIOType:
        if not args:
            return ResolvedIOType(io_type=IO.ANY, is_list_type=True)

        # Tuple[T1, T2, ...] — требуем одинаковую сигнатуру
        if origin in (tuple, Tuple) and len(args) > 1:
            resolved_elems = [self.resolve(a) for a in args]
            sig0 = (resolved_elems[0].io_type, resolved_elems[0].is_list_type, resolved_elems[0].is_literal_type)
            if not all((r.io_type, r.is_list_type, r.is_literal_type) == sig0 for r in resolved_elems):
                raise ValueError("Unsupported Tuple type: heterogeneous elements")
            inner = resolved_elems[0]
        else:
            inner = self.resolve(args[0])

        return ResolvedIOType(
            io_type=inner.io_type,
            options=inner.options,
            is_list_type=True,
            is_literal_type=inner.is_literal_type,
            is_optional=False,
            schema=inner.schema if inner.io_type is IO.SCHEMA else None
        )

    def _handle_dict_like(self, py_type: Any, origin: Any, args: tuple[Any, ...]) -> ResolvedIOType:
        if len(args) == 2:
            key_t, val_t = args

            val_res = self.resolve(val_t)
            if key_t in (str, Any) and val_res.io_type is IO.VARIABLE:
                return ResolvedIOType(io_type=IO.VARIABLE)

            val_schema = self._io_to_schema(val_res)

            has_constraints = bool(val_schema)
            if has_constraints:
                obj_schema = {
                    "type": "object",
                    "additionalProperties": val_schema,
                }
                if key_t in (str, Any):
                    obj_schema["propertyNames"] = {"type": "string"}

                return ResolvedIOType(io_type=IO.SCHEMA, schema=obj_schema)

        return ResolvedIOType(io_type=IO.DICT)

    def _handle_direct_mapping_or_unknown(self, py_type: Any, origin: Any, args: tuple[Any, ...]) -> ResolvedIOType:
        if py_type in self._type_map:
            return ResolvedIOType(io_type=self._type_map[py_type])
        if inspect.isclass(py_type) and origin is None:
            logger.warning(f"Unmapped class type {py_type}. Resolving as {IO.OBJECT}.")
            return ResolvedIOType(io_type=IO.OBJECT)
        raise ValueError(f"Unsupported Python type: {py_type}")

    def _handle_pydantic_model_via_type_adapter(self, py_type: Any) -> ResolvedIOType:
        schema = TypeAdapter(py_type).json_schema()
        return ResolvedIOType(io_type=IO.SCHEMA, schema=schema)

    # ---------- Вспомогательные ----------
    @staticmethod
    def _is_null_schema(node: dict) -> bool:
        t = node.get("type")
        if t == "null":
            return True
        return node.get("const", object()) is None

    def _deref(self, root: dict, ref: str) -> dict:
        if not ref.startswith("#/"):
            return {}
        parts = ref[2:].split("/")
        cur = root
        for p in parts:
            if p in cur:
                cur = cur[p]
            else:
                if p == "$defs" and "definitions" in cur:
                    cur = cur["definitions"]
                else:
                    return {}
        return cur

    def _io_to_schema(self, r: ResolvedIOType) -> dict:
        if r.io_type is IO.SCHEMA and r.schema is not None:
            return r.schema
        if r.io_type is IO.STRING:
            out = {"type": "string"}
            if r.is_literal_type and r.options:
                out["enum"] = list(r.options)
            return out
        if r.io_type is IO.INT:
            return {"type": "integer"}
        if r.io_type is IO.FLOAT:
            return {"type": "number"}
        if r.io_type is IO.BOOLEAN:
            return {"type": "boolean"}
        if r.io_type is IO.DICT:
            return {"type": "object"}
        if r.is_list_type:
            # Можно улучшить и прокинуть информацию об items, если она есть
            return {"type": "array", "items": {}}
        return {}

    def _is_union_annotation(self, t: Any) -> bool:
        try:
            if t is Union or get_origin(t) is Union or getattr(t, "__origin__", None) is Union:
                return True
        except Exception:
            pass

        rep = repr(t)
        if rep.startswith("typing.Union[") or rep.startswith("typing.Optional["):
            return True
        if " | " in rep and hasattr(t, "__args__"):
            return True

        return False

    def _resolve_string_annotation(self, annotation: str) -> Any | None:
        normalized = annotation.strip().strip("'\"")
        if not normalized:
            return None

        if "|" in normalized:
            parts = [self._resolve_string_annotation(part) for part in normalized.split("|")]
            if all(part is not None for part in parts):
                return Union[tuple(parts)]  # type: ignore[index]
            return None

        if normalized in {"None", "NoneType"}:
            return type(None)

        return self._type_name_map.get(normalized)
