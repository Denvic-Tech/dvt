from __future__ import annotations

from src.modules.sql_template.domain.gateways import (
    SQLIdentifierSerializerGateway,
    SQLLiteralSerializerGateway,
    SQLTemplateContextClassifierGateway,
    SQLTemplateTokenizerGateway,
)
from src.modules.sql_template.domain import SQLTemplateRenderingPolicy

from .use_cases import RenderSQLTemplateUseCase


class SQLTemplateProvider:
    def __init__(
        self,
        *,
        tokenizer: SQLTemplateTokenizerGateway,
        context_classifier: SQLTemplateContextClassifierGateway,
        literal_serializer: SQLLiteralSerializerGateway,
        identifier_serializer: SQLIdentifierSerializerGateway,
        policy: SQLTemplateRenderingPolicy = SQLTemplateRenderingPolicy(),
    ) -> None:
        self._tokenizer = tokenizer
        self._context_classifier = context_classifier
        self._literal_serializer = literal_serializer
        self._identifier_serializer = identifier_serializer
        self._policy = policy

    def create_render_sql_template_use_case(self) -> RenderSQLTemplateUseCase:
        return RenderSQLTemplateUseCase(
            tokenizer=self._tokenizer,
            context_classifier=self._context_classifier,
            literal_serializer=self._literal_serializer,
            identifier_serializer=self._identifier_serializer,
            policy=self._policy,
        )
