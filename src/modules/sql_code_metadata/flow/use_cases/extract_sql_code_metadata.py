from __future__ import annotations

from sqlalchemy.engine import Engine

from ...domain import SQLCodeMetadata
from ..gateways import SQLParserGateway, SQLResultMetadataGateway


class ExtractSQLCodeMetadataUseCase:
    """Извлекает полный metadata report по SQL-коду."""

    def __init__(
        self,
        *,
        parser_gateway: SQLParserGateway,
        result_metadata_gateway: SQLResultMetadataGateway,
    ) -> None:
        self.parser_gateway = parser_gateway
        self.result_metadata_gateway = result_metadata_gateway

    def execute(
        self,
        *,
        sql: str,
        connection: Engine,
        dialect_name: str | None = None,
    ) -> SQLCodeMetadata:
        effective_dialect_name = dialect_name or getattr(connection.dialect, "name", None)
        parsed_sql = self.parser_gateway.parse_sql(sql=sql, dialect_name=effective_dialect_name)
        statements = tuple(statement.metadata for statement in parsed_sql.statements)

        dataframe_metadata = None
        dataframe_metadata_statement_index = None
        for statement_index, parsed_statement in enumerate(parsed_sql.statements):
            if not parsed_statement.metadata.returns_data:
                continue

            dataframe_metadata = self.result_metadata_gateway.build_dataframe_metadata(
                parsed_statement=parsed_statement,
                dialect_name=parsed_sql.dialect_name,
                connection=connection,
            )
            dataframe_metadata_statement_index = statement_index
            break

        return SQLCodeMetadata(
            statements=statements,
            statement_count=len(statements),
            result_statement_count=sum(1 for statement in statements if statement.returns_data),
            dialect_name=parsed_sql.dialect_name,
            dataframe_metadata=dataframe_metadata,
            dataframe_metadata_statement_index=dataframe_metadata_statement_index,
        )
