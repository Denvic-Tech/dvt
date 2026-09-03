import dataclasses
import enum
from datetime import date, datetime, time
from decimal import Decimal
from typing import Union
from uuid import uuid4

import dask.dataframe as dd
import numpy as np
import pandas as pd
import pandas.testing as tm
import pytest
from pydantic import BaseModel

from core.dump_engine import DumpSerializationError, dump, load

from src.modules.data_catalog.domain import ColumnSchema, TableSchema
from src.utils.testing import types_testing_dataframe


class SampleEnum(enum.Enum):
    FIRST = "first"
    SECOND = "second"


@dataclasses.dataclass
class Nested:
    label: str
    values: tuple[int, ...]


@dataclasses.dataclass
class ComplexPayload:
    name: str
    created_at: datetime
    birthday: date
    wake_up: time
    balance: Decimal
    identifier: str
    tags: frozenset[str]
    nested: Nested
    flag: bool = True


class LeafAlpha(BaseModel):
    value: int


class LeafBeta(BaseModel):
    label: str


class NestedUnionModel(BaseModel):
    nested: Union[LeafAlpha, LeafBeta]


class RootUnionModel(BaseModel):
    payload: Union[LeafAlpha, NestedUnionModel]


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        42,
        3.14,
        "string",
        b"bytes",
    ],
)
def test_dump_load_primitives(value):
    packed = dump(value)
    unpacked = load(packed)
    assert unpacked == value


@pytest.mark.parametrize(
    "value",
    [
        np.int32(7),
        np.int64(8),
        np.float32(1.25),
        np.float64(2.5),
        np.bool_(True),
        np.datetime64("2026-08-21T10:30:00.123456789", "ns"),
        np.timedelta64(123456789, "ns"),
        np.str_("division"),
        np.bytes_(b"division"),
    ],
)
def test_dump_load_numpy_scalar_preserves_type_and_value(value):
    restored = load(dump(value))

    assert type(restored) is type(value)
    assert restored.dtype == value.dtype
    assert restored == value


def test_dump_load_complex_dataclass():
    payload = ComplexPayload(
        name="Test",
        created_at=datetime(2025, 1, 1, 12, 30, 45),
        birthday=date(1990, 5, 5),
        wake_up=time(7, 0, 0),
        balance=Decimal("123.45"),
        identifier=str(uuid4()),
        tags=frozenset({"alpha", "beta"}),
        nested=Nested(label="nested", values=(1, 2, 3)),
    )

    unpacked = load(dump(payload))
    assert isinstance(unpacked, ComplexPayload)
    assert unpacked == payload


def test_dump_load_table_schema():
    schema = TableSchema(
        columns=(
            ColumnSchema(
                name="customer_id",
                dtype="UUID",
                nullable=False,
                primary_key=True,
                metadata={"source": "registry"},
            ),
        )
    )

    restored = load(dump(schema))

    assert isinstance(restored, TableSchema)
    assert restored == schema


def test_dump_load_collections_and_enum():
    original = {
        SampleEnum.FIRST: [1, 2, 3],
        (1, 2): {"nested": {"set": {1, 2}}, "enum": SampleEnum.SECOND},
    }
    unpacked = load(dump(original))
    assert unpacked[SampleEnum.FIRST] == [1, 2, 3]
    assert isinstance(unpacked[(1, 2)]["enum"], SampleEnum)
    assert unpacked[(1, 2)]["enum"] is SampleEnum.SECOND
    assert unpacked[(1, 2)]["nested"]["set"] == {1, 2}


def test_dump_load_pandas_dataframe():
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    restored = load(dump(df))
    assert isinstance(restored, pd.DataFrame)
    tm.assert_frame_equal(restored, df, check_dtype=True)


def test_dump_load_dtypes_dataframe():
    df = types_testing_dataframe()
    dumped = dump(df)
    restored = load(dumped)
    assert isinstance(restored, pd.DataFrame)
    tm.assert_frame_equal(restored, df, check_dtype=True)


def test_dump_dask_dataframe_meta_mode():
    pdf = pd.DataFrame({"x": [1, 2, 3], "y": [4.0, 5.0, 6.0]})
    ddf = dd.from_pandas(pdf, npartitions=2)

    restored = load(dump(ddf, mode="meta"))
    assert isinstance(restored, dd.DataFrame)
    assert restored.npartitions == ddf.npartitions
    assert list(restored.columns) == list(ddf.columns)
    assert restored.compute().empty
    tm.assert_frame_equal(restored._meta, ddf._meta)


def test_dump_unsupported_type_raises_with_path():
    class Unserialisable:
        ...

    payload = {"items": [Unserialisable()]}

    with pytest.raises(DumpSerializationError) as exc_info:
        dump(payload)

    message = str(exc_info.value)
    assert "Unserialisable" in message
    assert "<root>" in message
    assert "['items']" in message
    assert "[0]" in message


def test_dump_load_pydantic_union_models_nested():
    original = RootUnionModel(payload=NestedUnionModel(nested=LeafBeta(label="beta")))

    restored = load(dump(original))

    assert isinstance(restored, RootUnionModel)
    assert isinstance(restored.payload, NestedUnionModel)
    assert isinstance(restored.payload.nested, LeafBeta)
    assert restored.payload.nested.label == "beta"
