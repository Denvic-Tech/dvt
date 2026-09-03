from __future__ import annotations

import re

import sqlglot

from src.modules.sql_template.domain import (
    SQLTemplateContextError,
    SQLTemplateInterpolationContext,
    SQLTemplateSyntaxError,
)
from src.modules.sql_template.infra.jinja_tokenizer import JinjaInterpolation


_TRAILING_WORD_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*$")


class SQLGlotContextClassifier:
    """Validates a SQL skeleton with SQLGlot and classifies supported tag positions."""

    def classify(
        self,
        template: str,
        interpolations: list[JinjaInterpolation],
        *,
        dialect_name: str | None,
    ) -> list[SQLTemplateInterpolationContext]:
        self._parse_skeleton(template, interpolations, dialect_name=dialect_name)
        return [self._classify_one(template, item) for item in interpolations]

    @staticmethod
    def _parse_skeleton(
        template: str,
        interpolations: list[JinjaInterpolation],
        *,
        dialect_name: str | None,
    ) -> None:
        chunks: list[str] = []
        previous = 0
        for index, item in enumerate(interpolations):
            chunks.append(template[previous:item.start])
            chunks.append(f"dvt_template_{index}")
            previous = item.end
        chunks.append(template[previous:])
        dialect = {"mssql": "tsql"}.get((dialect_name or "").lower(), dialect_name)
        try:
            sqlglot.parse("".join(chunks), read=dialect or None)
        except Exception as exc:
            raise SQLTemplateSyntaxError(f"SQL template syntax is invalid: {exc}") from exc

    @staticmethod
    def _classify_one(template: str, item: JinjaInterpolation) -> SQLTemplateInterpolationContext:
        if item.is_quoted_literal_content:
            return SQLTemplateInterpolationContext.QUOTED_LITERAL_CONTENT

        before = template[:item.start].upper()
        after = template[item.end:].upper()
        before_stripped = before.rstrip()
        after_stripped = after.lstrip()
        word_match = _TRAILING_WORD_RE.search(before_stripped)
        word = word_match.group(1) if word_match else ""

        if word in {"FROM", "JOIN", "INTO", "UPDATE", "TABLE", "SET"}:
            return SQLTemplateInterpolationContext.IDENTIFIER
        if re.search(r"\b(SELECT|GROUP\s+BY|ORDER\s+BY)\s*$", before_stripped):
            return SQLTemplateInterpolationContext.IDENTIFIER
        if re.search(r"\b(?:VALUES|IN)\s*\([^()]*$", before_stripped):
            return SQLTemplateInterpolationContext.LITERAL
        if before_stripped.endswith(",") and re.match(
            r"(?:,|FROM\b|AS\b|\)|ASC\b|DESC\b|LIMIT\b|OFFSET\b|WHERE\b|HAVING\b|=)",
            after_stripped,
        ):
            return SQLTemplateInterpolationContext.IDENTIFIER
        if (
            "INSERT" in before
            and before_stripped.endswith("(")
            and re.match(r"\s*\)\s*VALUES\b", after)
        ):
            return SQLTemplateInterpolationContext.IDENTIFIER

        if word in {"LIMIT", "OFFSET", "FETCH"}:
            return SQLTemplateInterpolationContext.LITERAL
        if re.search(r"(?:=|<>|!=|<=|>=|<|>)\s*$", before_stripped):
            return SQLTemplateInterpolationContext.LITERAL

        raise SQLTemplateContextError(
            "SQL template interpolation is not in a supported literal or identifier position. "
            "Raw SQL fragments are not supported."
        )
