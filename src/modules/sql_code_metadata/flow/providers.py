from __future__ import annotations

from .gateways import SQLParserGateway, SQLResultMetadataGateway
from .use_cases import ExtractSQLCodeMetadataUseCase, ValidateSQLUseCase


class SQLCodeMetadataProvider:
    """Собирает зависимости use case-ов анализа SQL-кода."""

    def __init__(
        self,
        *,
        parser_gateway: SQLParserGateway,
        result_metadata_gateway: SQLResultMetadataGateway | None = None,
    ) -> None:
        self.parser_gateway = parser_gateway
        self.result_metadata_gateway = result_metadata_gateway

    def create_validate_sql_use_case(self) -> ValidateSQLUseCase:
        return ValidateSQLUseCase(parser_gateway=self.parser_gateway)

    def create_extract_sql_code_metadata_use_case(self) -> ExtractSQLCodeMetadataUseCase:
        if self.result_metadata_gateway is None:
            raise ValueError("result_metadata_gateway is required for SQL metadata extraction.")

        return ExtractSQLCodeMetadataUseCase(
            parser_gateway=self.parser_gateway,
            result_metadata_gateway=self.result_metadata_gateway,
        )
