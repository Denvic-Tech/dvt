"""Diagnostics collected by pure checks and rendered at the preparation boundary."""

from dataclasses import dataclass, field
from typing import Any

from ..errors import AIMCPHTTPError
from .references import ResolvedPatch

Diagnostic = dict[str, Any]


@dataclass
class Diagnostics:
    errors: list[Diagnostic] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)

    def raise_if_invalid(self, references: ResolvedPatch) -> None:
        if self.errors:
            raise AIMCPHTTPError(
                422,
                "GRAPH_VALIDATION_FAILED",
                "Graph changes did not pass validation.",
                details=references.diagnostics({"errors": self.errors, "warnings": self.warnings}),
            )
