import pytest

from src.modules.data_catalog.domain import (
    ColumnSchema,
    InvalidColumnSchemaError,
    InvalidTableSchemaError,
    TableSchema,
)


def test_column_schema_normalizes_text_and_copies_metadata() -> None:
    metadata = {"source": "registry"}

    column = ColumnSchema(
        name="  customer_id  ",
        dtype="  UUID  ",
        description="   ",
        format=" uuid ",
        metadata=metadata,
    )
    metadata["source"] = "changed"

    assert column.name == "customer_id"
    assert column.dtype == "UUID"
    assert column.description is None
    assert column.format == "uuid"
    assert column.metadata == {"source": "registry"}


@pytest.mark.parametrize(
    ("kwargs", "error_fragment"),
    [
        ({"name": "   "}, "non-empty"),
        ({"name": "amount", "precision": -1}, "non-negative"),
        ({"name": "amount", "precision": 2, "scale": 3}, "greater than precision"),
        ({"name": "id", "nullable": 1}, "boolean"),
    ],
)
def test_column_schema_rejects_invalid_values(
    kwargs: dict[str, object], error_fragment: str
) -> None:
    with pytest.raises(InvalidColumnSchemaError) as exc_info:
        ColumnSchema(**kwargs)

    assert error_fragment in str(exc_info.value.exc_data)


def test_table_schema_rejects_duplicate_column_names() -> None:
    with pytest.raises(InvalidTableSchemaError) as exc_info:
        TableSchema(columns=(ColumnSchema(name="id"), ColumnSchema(name="id")))

    assert "duplicate column names" in str(exc_info.value.exc_data)
