from __future__ import annotations

from src.modules.sql_template.domain import (
    SQLTemplateInterpolationContext,
    SQLTemplateRenderRequest,
    SQLTemplateRenderResult,
    SQLTemplateRenderingPolicy,
)
from src.modules.sql_template.domain.gateways import (
    SQLIdentifierSerializerGateway,
    SQLLiteralSerializerGateway,
    SQLTemplateContextClassifierGateway,
    SQLTemplateTokenizerGateway,
)


class RenderSQLTemplateUseCase:
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

    def execute(self, request: SQLTemplateRenderRequest) -> SQLTemplateRenderResult:
        interpolations = self._tokenizer.tokenize(request.template)
        if not interpolations:
            return SQLTemplateRenderResult(sql=request.template)
        contexts = self._context_classifier.classify(
            request.template,
            interpolations,
            dialect_name=request.dialect_name,
        )
        chunks: list[str] = []
        position = 0
        for interpolation, context in zip(interpolations, contexts, strict=True):
            chunks.append(request.template[position:interpolation.start])
            value = request.expression_evaluator.evaluate(
                interpolation.expression,
                variables=request.variables,
                project_variables=request.project_variables,
            )
            if context is SQLTemplateInterpolationContext.QUOTED_LITERAL_CONTENT:
                chunks.append(self._literal_serializer.escape_quoted_content(value))
            elif context is SQLTemplateInterpolationContext.LITERAL:
                chunks.append(self._literal_serializer.serialize(value, dialect_name=request.dialect_name))
            else:
                chunks.append(self._identifier_serializer.serialize(value, dialect_name=request.dialect_name))
            position = interpolation.end
        chunks.append(request.template[position:])
        return SQLTemplateRenderResult(sql="".join(chunks))
