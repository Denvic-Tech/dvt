from __future__ import annotations

from ...domain import SQLCodeMetadata, SQLValidationError, SQLValidationPolicy
from ..gateways import SQLParserGateway


class ValidateSQLUseCase:
    """Применяет policy-based правила к структурно разобранному SQL."""

    DDL_FORBIDDEN_MESSAGE = "DDL statements are forbidden."
    DATA_MUTATING_FORBIDDEN_MESSAGE = "Data mutating statements are forbidden."
    MULTIPLE_STATEMENTS_FORBIDDEN_MESSAGE = "Multiple SQL statements are not allowed."
    MULTIPLE_RESULT_STATEMENTS_FORBIDDEN_MESSAGE = "Multiple result-returning statements are not allowed."
    RESULT_STATEMENT_REQUIRED_MESSAGE = "A result-returning statement is required."
    SINGLE_RESULT_STATEMENT_REQUIRED_MESSAGE = "Exactly one result-returning statement is required."

    def __init__(self, *, parser_gateway: SQLParserGateway) -> None:
        self.parser_gateway = parser_gateway

    def execute(
        self,
        *,
        sql: str,
        policy: SQLValidationPolicy,
        dialect_name: str | None = None,
    ) -> SQLCodeMetadata | None:
        if not self._needs_structural_analysis(policy):
            return None

        parsed_sql = self.parser_gateway.parse_sql(sql=sql, dialect_name=dialect_name)
        statements = tuple(statement.metadata for statement in parsed_sql.statements)
        report = SQLCodeMetadata(
            statements=statements,
            statement_count=len(statements),
            result_statement_count=sum(1 for statement in statements if statement.returns_data),
            dialect_name=parsed_sql.dialect_name,
        )
        self._validate_report(report=report, policy=policy)
        return report

    def _needs_structural_analysis(self, policy: SQLValidationPolicy) -> bool:
        return any(
            (
                policy.validate_parseability,
                not policy.allow_multiple_statements,
                not policy.allow_multiple_result_statements,
                policy.require_result_statement,
                policy.require_single_result_statement,
                policy.forbid_ddl_statements,
                policy.forbid_data_mutating_statements,
                policy.allowed_statement_types is not None,
                policy.forbidden_statement_types is not None,
            )
        )

    def _validate_report(self, *, report: SQLCodeMetadata, policy: SQLValidationPolicy) -> None:
        if not policy.allow_multiple_statements and report.statement_count > 1:
            raise SQLValidationError(self.MULTIPLE_STATEMENTS_FORBIDDEN_MESSAGE)

        if not policy.allow_multiple_result_statements and report.result_statement_count > 1:
            raise SQLValidationError(self.MULTIPLE_RESULT_STATEMENTS_FORBIDDEN_MESSAGE)

        if policy.allowed_statement_types is not None:
            for statement in report.statements:
                if statement.statement_type not in policy.allowed_statement_types:
                    raise SQLValidationError(
                        f"SQL statement type '{statement.statement_type}' is not allowed."
                    )

        if policy.forbidden_statement_types is not None:
            for statement in report.statements:
                if statement.statement_type in policy.forbidden_statement_types:
                    raise SQLValidationError(
                        f"SQL statement type '{statement.statement_type}' is not allowed."
                    )

        if policy.forbid_ddl_statements:
            for statement in report.statements:
                if statement.category == "ddl":
                    raise SQLValidationError(self.DDL_FORBIDDEN_MESSAGE)

        if policy.forbid_data_mutating_statements:
            for statement in report.statements:
                if statement.category == "data_mutating":
                    raise SQLValidationError(self.DATA_MUTATING_FORBIDDEN_MESSAGE)

        if policy.require_result_statement and report.result_statement_count == 0:
            raise SQLValidationError(self.RESULT_STATEMENT_REQUIRED_MESSAGE)

        if policy.require_single_result_statement and report.result_statement_count != 1:
            raise SQLValidationError(self.SINGLE_RESULT_STATEMENT_REQUIRED_MESSAGE)
