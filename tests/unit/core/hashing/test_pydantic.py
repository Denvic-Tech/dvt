from pydantic import BaseModel

from core.hashing._pydantic import _get_pydantic_model_hash, _get_pydantic_object_hash


class AlphaModel(BaseModel):
    value: int


class BetaModel(BaseModel):
    value: int


def test_pydantic_object_hash_changes_with_data():
    a = AlphaModel(value=1)
    b = AlphaModel(value=2)

    assert _get_pydantic_object_hash(a) != _get_pydantic_object_hash(b)


def test_pydantic_object_hash_changes_with_class():
    a = AlphaModel(value=1)
    b = BetaModel(value=1)

    assert _get_pydantic_object_hash(a) != _get_pydantic_object_hash(b)


def test_pydantic_model_hash_stable_and_distinct():
    assert _get_pydantic_model_hash(AlphaModel) == _get_pydantic_model_hash(AlphaModel)
    assert _get_pydantic_model_hash(AlphaModel) != _get_pydantic_model_hash(BetaModel)
