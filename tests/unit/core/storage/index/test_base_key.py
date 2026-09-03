from dataclasses import FrozenInstanceError, is_dataclass
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from core.storage.index import IndexKeyBase


class ExampleKey(IndexKeyBase):
    user_id: str
    project_id: str | None = None
    executed_at: datetime | None = None


class DetailedKey(IndexKeyBase):
    user_id: str
    project_id: str | None = None
    node_index: int | None = None
    unique_id: UUID | None = None


class SimpleKey(IndexKeyBase):
    user_id: str
    project_id: str | None = None
    node_id: str | None = None


def test_index_key_meta_creates_frozen_slots_dataclass():
    assert is_dataclass(ExampleKey)
    assert ExampleKey.__dataclass_params__.frozen
    assert ExampleKey.__slots__ == ("user_id", "project_id", "executed_at")

    key = ExampleKey(user_id="user-1", project_id="project-1", executed_at=datetime(2025, 1, 1))
    with pytest.raises(FrozenInstanceError):
        key.user_id = "user-2"


def test_invalid_field_type_raises_type_error():
    with pytest.raises(TypeError):

        class InvalidKey(IndexKeyBase):
            payload: dict | None = None


def test_to_segments_full_key():
    unique = uuid4()
    key = DetailedKey(
        user_id="user-1",
        project_id="project-1",
        node_index=5,
        unique_id=unique,
    )

    assert key.to_segments(ensure_full=True) == [
        "detailed_key",
        "user-1",
        "project-1",
        5,
        unique,
    ]


def test_to_segments_stops_at_first_none():
    key = DetailedKey(user_id="user-1", project_id=None, node_index=None, unique_id=None)
    assert key.to_segments() == ["detailed_key", "user-1"]


def test_to_segments_rejects_gapped_prefix():
    key = DetailedKey(user_id="user-1", project_id=None, node_index=1, unique_id=None)
    with pytest.raises(ValueError, match="gapped prefix"):
        key.to_segments()


def test_to_segments_requires_full_key_when_requested():
    key = DetailedKey(user_id="user-1", project_id=None, node_index=None, unique_id=None)
    with pytest.raises(ValueError, match="full key required"):
        key.to_segments(ensure_full=True)


def test_to_segments_requires_first_field():
    key = DetailedKey(user_id=None, project_id=None, node_index=None, unique_id=None)
    with pytest.raises(ValueError, match="first field must be provided"):
        key.to_segments()


def test_to_str_joins_segments_with_separator():
    key = SimpleKey(user_id="user-1", project_id="project-1", node_id="node-1")
    assert key.to_str(sep=":", ensure_full=False) == "simple_key:user-1:project-1:node-1"
