from typing import Literal, TypeAlias


SQLStatementType: TypeAlias = str
SQLStatementCategory: TypeAlias = Literal[
    "read_only",
    "data_mutating",
    "ddl",
    "execution",
    "unknown",
]
