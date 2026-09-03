from __future__ import annotations

from dataclasses import dataclass

from src.modules.sql_template.domain import SQLTemplateSyntaxError


@dataclass(frozen=True)
class JinjaInterpolation:
    start: int
    end: int
    expression: str
    is_quoted_literal_content: bool


class JinjaInterpolationTokenizer:
    """Finds interpolation tokens without evaluating user supplied Jinja code."""

    def tokenize(self, template: str) -> list[JinjaInterpolation]:
        result: list[JinjaInterpolation] = []
        index = 0
        in_single_quote = False
        while index < len(template):
            char = template[index]
            if char == "'":
                if in_single_quote and index + 1 < len(template) and template[index + 1] == "'":
                    index += 2
                    continue
                in_single_quote = not in_single_quote
                index += 1
                continue
            if template.startswith("{{", index):
                end = template.find("}}", index + 2)
                if end == -1:
                    raise SQLTemplateSyntaxError("SQL template contains an unclosed Jinja interpolation.")
                expression = template[index + 2:end].strip()
                if not expression:
                    raise SQLTemplateSyntaxError("SQL template contains an empty Jinja interpolation.")
                result.append(
                    JinjaInterpolation(
                        start=index,
                        end=end + 2,
                        expression=expression,
                        is_quoted_literal_content=in_single_quote,
                    )
                )
                index = end + 2
                continue
            index += 1
        if in_single_quote:
            raise SQLTemplateSyntaxError("SQL template contains an unclosed string literal.")
        return result
