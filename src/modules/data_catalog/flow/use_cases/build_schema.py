from collections.abc import Iterable

from ...domain import ColumnSchema, TableSchema


class BuildSchema:
    def execute(self, columns: Iterable[ColumnSchema]) -> TableSchema:
        indexed_columns = list(enumerate(columns))
        if any(column.order is not None for _, column in indexed_columns):
            indexed_columns.sort(
                key=lambda item: (
                    item[1].order is None,
                    item[1].order if item[1].order is not None else 0,
                    item[0],
                )
            )
        return TableSchema(columns=tuple(column for _, column in indexed_columns))
