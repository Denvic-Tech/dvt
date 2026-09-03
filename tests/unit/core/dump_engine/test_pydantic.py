from typing import Annotated, Union

import pytest
from pydantic import BaseModel

from core.dump_engine._pydantic import PydanticModelCacheEngine


class LeafAlpha(BaseModel):
    value: int


class LeafBeta(BaseModel):
    label: str


class Container(BaseModel):
    payload: Annotated[Union[LeafAlpha, LeafBeta], "payload"]


class Outer(BaseModel):
    child: Container


class BaseWithUnion(BaseModel):
    node: Union[LeafAlpha, LeafBeta]


class DerivedWithUnion(BaseWithUnion):
    extra: int


def test_can_handle_pydantic_model():
    engine = PydanticModelCacheEngine()

    assert engine.can_handle(LeafAlpha(value=1)) is True
    assert engine.can_handle({"value": 1}) is False


def test_dump_load_simple_model_roundtrip():
    engine = PydanticModelCacheEngine()

    model = LeafBeta(label="beta")
    data, meta = engine.dump(model)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored, LeafBeta)
    assert restored.label == "beta"


def test_dump_load_restores_union_models_nested_annotated():
    engine = PydanticModelCacheEngine()

    model = Outer(child=Container(payload=LeafBeta(label="nested")))
    data, meta = engine.dump(model)

    assert meta is not None
    assert "union_models" in meta
    assert any(entry.get("path") == ["child", "payload"] for entry in meta["union_models"])

    restored = engine.load(data, meta=meta)

    assert isinstance(restored, Outer)
    assert isinstance(restored.child.payload, LeafBeta)
    assert restored.child.payload.label == "nested"


def test_dump_load_restores_union_model_from_base_class():
    engine = PydanticModelCacheEngine()

    model = DerivedWithUnion(node=LeafAlpha(value=42), extra=7)
    data, meta = engine.dump(model)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored, DerivedWithUnion)
    assert isinstance(restored.node, LeafAlpha)
    assert restored.node.value == 42
    assert restored.extra == 7


def test_load_requires_meta():
    engine = PydanticModelCacheEngine()

    model = LeafAlpha(value=10)
    data, _ = engine.dump(model)

    with pytest.raises(ValueError):
        engine.load(data, meta=None)
