import logging
from unittest.mock import Mock

import pytest
import sqlalchemy as sa

from core.metadata.db_metadata import load_db_table_metadata
from core.metadata.db_metadata.comments import load_table_comment, normalize_comment
from core.types import DataFrameMetadata


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        (" ", " "),
        ("  Клиент\nO'Brien\t", "  Клиент\nO'Brien\t"),
    ],
)
def test_normalize_comment_preserves_documentation(value, expected):
    assert normalize_comment(value) == expected


def test_reflected_comments_survive_metadata_serialization(monkeypatch):
    inspector = Mock()
    inspector.has_table.return_value = True
    inspector.get_pk_constraint.return_value = {}
    inspector.get_indexes.return_value = []
    inspector.get_columns.return_value = [
        {"name": "ID", "type": sa.Integer(), "comment": "Первичный ключ"},
        {"name": "id", "type": sa.Integer(), "comment": ""},
        {"name": "value", "type": sa.String()},
    ]
    inspector.get_table_comment.return_value = {"text": "  Клиенты\nОписание  "}
    monkeypatch.setattr(sa, "inspect", lambda engine: inspector)
    table = load_db_table_metadata(object(), table_name="Customers", schema_name="Analytics")
    assert [c.comment for c in table.columns] == ["Первичный ключ", None, None]
    metadata = DataFrameMetadata(columns=table.columns, comment=table.comment)
    restored = DataFrameMetadata.model_validate_json(metadata.model_dump_json())
    assert restored.comment == "  Клиенты\nОписание  "
    assert [c.comment for c in restored.columns] == ["Первичный ключ", None, None]
    inspector.get_table_comment.assert_called_once_with("Customers", schema="Analytics")


@pytest.mark.parametrize(
    "failure",
    [
        NotImplementedError(),
        sa.exc.OperationalError(
            "SELECT secret",
            {},
            Exception("password=private"),
        ),
        OSError("password=private"),
    ],
)
def test_optional_comment_failure_does_not_disclose_driver_details(failure, caplog):
    inspector = Mock()
    inspector.get_table_comment.side_effect = failure
    with caplog.at_level(logging.WARNING):
        assert load_table_comment(inspector, "customers") is None
    assert "private" not in caplog.text
    assert "SELECT" not in caplog.text
    if not isinstance(failure, NotImplementedError):
        assert "Unable to read optional" in caplog.text


def test_structural_reflection_error_is_not_suppressed(monkeypatch):
    inspector = Mock()
    inspector.has_table.return_value = True
    inspector.get_pk_constraint.return_value = {}
    inspector.get_indexes.return_value = []
    inspector.get_columns.side_effect = sa.exc.OperationalError("structure", {}, Exception())
    monkeypatch.setattr(sa, "inspect", lambda engine: inspector)
    with pytest.raises(sa.exc.OperationalError):
        load_db_table_metadata(object(), table_name="customers")
    inspector.get_table_comment.assert_not_called()


def test_old_dataframe_metadata_defaults_to_no_comments():
    metadata = DataFrameMetadata.model_validate(
        {
            "type": "DATAFRAME",
            "columns": [{"name": "id", "dtype": "INT"}],
        }
    )
    assert metadata.comment is None
    assert metadata.columns[0].comment is None
