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
        top_literal_positions = self._parse_skeleton(
            template, interpolations, dialect_name=dialect_name
        )
        return [
            SQLTemplateInterpolationContext.LITERAL
            if item.start in top_literal_positions
            else self._classify_one(template, item)
            for item in interpolations
        ]

    @staticmethod
    def _parse_skeleton(
        template: str,
        interpolations: list[JinjaInterpolation],
        *,
        dialect_name: str | None,
    ) -> set[int]:
        chunks: list[str] = []
        placeholder_positions: dict[int, int] = {}
        previous = 0
        skeleton_offset = 0
        for index, item in enumerate(interpolations):
            prefix = template[previous:item.start]
            placeholder = f"dvt_template_{index}"
            chunks.extend((prefix, placeholder))
            placeholder_positions[skeleton_offset + len(prefix)] = item.start
            skeleton_offset += len(prefix) + len(placeholder)
            previous = item.end
        chunks.append(template[previous:])
        dialect = {"mssql": "tsql"}.get((dialect_name or "").lower(), dialect_name)
        try:
            statements = sqlglot.parse("".join(chunks), read=dialect or None)
        except Exception as exc:
            raise SQLTemplateSyntaxError(f"SQL template syntax is invalid: {exc}") from exc

        top_literal_positions: set[int] = set()
        if (dialect or "").lower() != "tsql":
            return top_literal_positions
        for statement in statements:
            if statement is None:
                continue
            # SQLGlot represents TOP as Limit; accept only a standalone placeholder value.
            for limit in statement.find_all(sqlglot.exp.Limit):
                value = limit.expression
                while isinstance(value, sqlglot.exp.Paren):
                    value = value.this
                if not isinstance(value, sqlglot.exp.Column) or len(value.parts) != 1:
                    continue
                identifier = value.this
                if identifier.quoted:
                    continue
                # Match token offsets, not names: user SQL may contain dvt_template_N itself.
                skeleton_position = identifier.meta.get("start")
                if skeleton_position in placeholder_positions:
                    top_literal_positions.add(placeholder_positions[skeleton_position])
        return top_literal_positions

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
