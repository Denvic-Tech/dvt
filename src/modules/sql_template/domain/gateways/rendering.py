from __future__ import annotations

from typing import Any, Protocol


class SQLTemplateTokenizerGateway(Protocol):
    def tokenize(self, template: str) -> list[Any]: ...


class SQLTemplateContextClassifierGateway(Protocol):
    def classify(self, template: str, interpolations: list[Any], *, dialect_name: str | None) -> list[Any]: ...


class SQLLiteralSerializerGateway(Protocol):
    def serialize(self, value: Any, *, dialect_name: str | None) -> str: ...

    def escape_quoted_content(self, value: Any) -> str: ...


class SQLIdentifierSerializerGateway(Protocol):
    def serialize(self, value: Any, *, dialect_name: str | None) -> str: ...
