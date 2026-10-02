"""Safe, recursive Arrow dtype transport. No evaluation of Python type strings."""

from typing import Literal

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, model_validator


class ArrowFieldMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    nullable: bool = True
    type: "ArrowTypeMetadata"


class ArrowTypeMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal[
        "scalar",
        "timestamp",
        "duration",
        "decimal",
        "list",
        "large_list",
        "fixed_size_list",
        "struct",
        "fixed_size_binary",
    ]
    name: str | None = None
    unit: Literal["s", "ms", "us", "ns"] | None = None
    timezone: str | None = None
    precision: int | None = None
    scale: int | None = None
    size: int | None = None
    fields: tuple[ArrowFieldMetadata, ...] = ()

    @model_validator(mode="after")
    def validate_shape(self):
        if self.kind in {"list", "large_list", "fixed_size_list"} and len(self.fields) != 1:
            raise ValueError("Arrow list requires exactly one value field")
        return self


def arrow_type_to_metadata(dtype: pa.DataType) -> ArrowTypeMetadata:
    if pa.types.is_struct(dtype):
        kind, fields = "struct", list(dtype)
    elif (
        pa.types.is_list(dtype)
        or pa.types.is_large_list(dtype)
        or pa.types.is_fixed_size_list(dtype)
    ):
        kind = (
            "list"
            if pa.types.is_list(dtype)
            else "large_list"
            if pa.types.is_large_list(dtype)
            else "fixed_size_list"
        )
        fields = [dtype.value_field]
    else:
        if pa.types.is_timestamp(dtype):
            return ArrowTypeMetadata(kind="timestamp", unit=dtype.unit, timezone=dtype.tz)
        if pa.types.is_duration(dtype):
            return ArrowTypeMetadata(kind="duration", unit=dtype.unit)
        if pa.types.is_decimal(dtype):
            return ArrowTypeMetadata(
                kind="decimal",
                name=str(dtype.bit_width),
                precision=dtype.precision,
                scale=dtype.scale,
            )
        if pa.types.is_fixed_size_binary(dtype):
            return ArrowTypeMetadata(kind="fixed_size_binary", size=dtype.byte_width)
        # Only supported public Arrow aliases; never use eval.
        pa.type_for_alias(str(dtype))
        return ArrowTypeMetadata(kind="scalar", name=str(dtype))
    return ArrowTypeMetadata(
        kind=kind,
        size=dtype.list_size if pa.types.is_fixed_size_list(dtype) else None,
        fields=tuple(
            ArrowFieldMetadata(
                name=f.name, nullable=f.nullable, type=arrow_type_to_metadata(f.type)
            )
            for f in fields
        ),
    )


def arrow_type_from_metadata(metadata: ArrowTypeMetadata) -> pa.DataType:  # noqa: PLR0911
    # Explicit cases keep this safe type decoder auditable.
    if metadata.kind == "scalar":
        return pa.type_for_alias(metadata.name)
    if metadata.kind == "timestamp":
        return pa.timestamp(metadata.unit, tz=metadata.timezone)
    if metadata.kind == "duration":
        return pa.duration(metadata.unit)
    if metadata.kind == "decimal":
        factories = {
            "32": pa.decimal32,
            "64": pa.decimal64,
            "128": pa.decimal128,
            "256": pa.decimal256,
        }
        if metadata.name not in factories:
            raise ValueError("Unsupported Arrow decimal width")
        return factories[metadata.name](metadata.precision, metadata.scale)
    if metadata.kind == "fixed_size_binary":
        return pa.binary(metadata.size)
    fields = [
        pa.field(f.name, arrow_type_from_metadata(f.type), nullable=f.nullable)
        for f in metadata.fields
    ]
    if metadata.kind == "struct":
        return pa.struct(fields)
    if metadata.kind == "large_list":
        return pa.large_list(fields[0])
    if metadata.kind == "fixed_size_list":
        return pa.list_(fields[0], metadata.size)
    return pa.list_(fields[0])
