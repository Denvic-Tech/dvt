from src.modules.data_catalog.domain import ColumnSchema
from src.modules.data_catalog.flow import BuildSchema


def test_build_schema_preserves_input_order_when_order_is_not_configured() -> None:
    schema = BuildSchema().execute([ColumnSchema(name="second"), ColumnSchema(name="first")])

    assert [column.name for column in schema.columns] == ["second", "first"]


def test_build_schema_sorts_stably_by_explicit_order() -> None:
    schema = BuildSchema().execute(
        [
            ColumnSchema(name="third", order=2),
            ColumnSchema(name="first", order=1),
            ColumnSchema(name="second", order=1),
        ]
    )

    assert [column.name for column in schema.columns] == ["first", "second", "third"]
