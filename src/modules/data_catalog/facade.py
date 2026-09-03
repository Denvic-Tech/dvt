import dask.dataframe as dd

from .domain import TableSchema
from .flow import BuildSchema
from .infra import DataFrameSchemaMapper, DataFrameSchemaMapping


def build_table_schema_from_dataframe(
    *,
    dataframe: dd.DataFrame,
    mapping: DataFrameSchemaMapping,
) -> TableSchema:
    columns = DataFrameSchemaMapper().to_columns(dataframe=dataframe, mapping=mapping)
    return BuildSchema().execute(columns)
