from __future__ import annotations

import pytest

from src.node_dsl import BaseNode, NodeValidationError, OutputField
from src.node_dsl.node_mixins.sql import SQLCodeInputFieldMixin
from src.node_dsl.variables import make_unresolved_value
from src.modules.sql_code_metadata import SQLValidationPolicy


class _DefaultSQLNode(SQLCodeInputFieldMixin, BaseNode):
    """Тестовая нода с default SQL validation policy."""

    output_flag: bool = OutputField()

    def process(self) -> None:
        """Записывает тестовый output без побочных эффектов."""

        self.output_flag = True


class _RelaxedSQLNode(SQLCodeInputFieldMixin, BaseNode):
    """Тестовая нода с разрешёнными multi-statement и multi-result запросами."""

    SQL_VALIDATION_POLICY = SQLValidationPolicy(
        allow_multiple_statements=True,
        allow_multiple_result_statements=True,
    )

    output_flag: bool = OutputField()

    def process(self) -> None:
        """Записывает тестовый output без побочных эффектов."""

        self.output_flag = True


class _MSSQLOutputNode(SQLCodeInputFieldMixin, BaseNode):
    """Тестовая нода, явно задающая dialect для MSSQL OUTPUT."""

    SQL_VALIDATION_POLICY = SQLValidationPolicy(require_result_statement=True)

    output_flag: bool = OutputField()

    def process(self) -> None:
        """Записывает тестовый output без побочных эффектов."""

        self.output_flag = True

    def get_dialect_name_for_sql_code_metadata(self) -> str | None:
        """Возвращает dialect name для MSSQL-specific parsing."""

        return "mssql"


def _build_node(node_class: type[BaseNode], *, sql_code) -> BaseNode:
    """Создаёт тестовую ноду с минимально необходимым runtime context."""

    return node_class(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-1",
        sql_code=sql_code,
    )


@pytest.mark.asyncio
async def test_sql_code_input_field_mixin_rejects_empty_sql() -> None:
    """Отклоняет пустой SQL тем же коротким сообщением, что и раньше."""

    node = _build_node(_DefaultSQLNode, sql_code="   ")

    with pytest.raises(NodeValidationError, match="SQL code is empty."):
        await node.validate()


@pytest.mark.asyncio
async def test_sql_code_input_field_mixin_skips_unresolved_values() -> None:
    """Не запускает strict parsing для unresolved placeholders."""

    node = _build_node(
        _DefaultSQLNode,
        sql_code=make_unresolved_value(reason="missing sql", declared_type="STRING"),
    )

    await node.validate()


@pytest.mark.asyncio
async def test_sql_code_input_field_mixin_uses_policy_override_for_multiple_statements() -> None:
    """Позволяет subclass policy переопределить multi-statement behavior."""

    node = _build_node(_RelaxedSQLNode, sql_code="SELECT 1; SELECT 2")

    await node.validate()


@pytest.mark.asyncio
async def test_sql_code_input_field_mixin_uses_dialect_hook_for_mssql_output() -> None:
    """Использует dialect hook для MSSQL OUTPUT вместо generic fallback."""

    generic_node = _build_node(
        _DefaultSQLNode,
        sql_code="INSERT INTO t(id) OUTPUT INSERTED.id VALUES (1)",
    )
    mssql_node = _build_node(
        _MSSQLOutputNode,
        sql_code="INSERT INTO t(id) OUTPUT INSERTED.id VALUES (1)",
    )

    with pytest.raises(NodeValidationError, match="SQL contains syntax errors."):
        await generic_node.validate()

    await mssql_node.validate()
