"""Gateway-протоколы анализа SQL-кода."""

from .parser import ParsedSQLCode, ParsedSQLStatement, SQLParserGateway
from .result_metadata import SQLResultMetadataGateway

__all__ = [
    "ParsedSQLCode",
    "ParsedSQLStatement",
    "SQLParserGateway",
    "SQLResultMetadataGateway",
]
