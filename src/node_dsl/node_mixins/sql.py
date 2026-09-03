from typing import Any, ClassVar

from src.modules.sql_code_metadata import (
    SQLAlchemyResultMetadataGateway,
    SQLCodeMetadata,
    SQLCodeMetadataProvider,
    SQLGlotParserGateway,
    SQLValidationError,
    SQLValidationPolicy,
)
from src.node_dsl.exceptions import NodeValidationError
from src.node_dsl.field import InputField
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_mixins.base import NodeFieldsMixin
from src.node_dsl.variables import is_unresolved_value


class SQLCodeInputFieldMixin(NodeFieldsMixin):
    """Добавляет SQL input field и policy-based structural validation."""

    SQL_EMPTY_VALIDATION_MESSAGE = "SQL code is empty."
    SQL_EMPTY_PROCESS_MESSAGE = "SQL code is empty."
    SQL_VALIDATION_POLICY: ClassVar[SQLValidationPolicy] = SQLValidationPolicy()

    ALLOW_NULLABLE_SQL_CODE: ClassVar[bool] = False

    _sql_validation_provider: ClassVar = SQLCodeMetadataProvider(
        parser_gateway=SQLGlotParserGateway(),
        result_metadata_gateway=SQLAlchemyResultMetadataGateway(),
    ).create_validate_sql_use_case()

    sql_code: str = InputField(
        multiline=True,
        expression_policy="default",
        sql_template=True,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self._sql_code_metadata: SQLCodeMetadata | None = None

    def _normalize_sql(self) -> str:
        """Нормализует SQL для использования в process-логике."""

        if not self.sql_code:
            raise ValueError(self.SQL_EMPTY_PROCESS_MESSAGE)

        normalized_sql = str(self.sql_code).strip().rstrip(";")
        if not normalized_sql:
            raise ValueError(self.SQL_EMPTY_PROCESS_MESSAGE)

        return normalized_sql

    def get_dialect_name_for_sql_code_metadata(self) -> str | None:
        """Возвращает dialect name для извлечения метаданных SQL кода при явном opt-in."""

        return None

    def should_validate_sql_code(self) -> bool:
        """Позволяет узлам условно отключать общий SQL validation hook."""

        return True

    def ensure_sql_code_metadata(self) -> SQLCodeMetadata:
        if self._sql_code_metadata is not None and isinstance(self._sql_code_metadata, SQLCodeMetadata):
            return self._sql_code_metadata


        sql_value = self.sql_code

        if self.ALLOW_NULLABLE_SQL_CODE and sql_value is None:
            pass

        if not sql_value or sql_value is Ellipsis:
            raise NodeValidationError(self.SQL_EMPTY_VALIDATION_MESSAGE)
        if is_unresolved_value(sql_value):
            return

        if not isinstance(sql_value, str):
            return

        normalized_sql = sql_value.strip().rstrip(";")
        if not normalized_sql:
            raise NodeValidationError(self.SQL_EMPTY_VALIDATION_MESSAGE)

        try:
            self._sql_code_metadata = self._sql_validation_provider.execute(
                sql=normalized_sql,
                policy=self.SQL_VALIDATION_POLICY,
                dialect_name=self.get_dialect_name_for_sql_code_metadata(),
            )
        except SQLValidationError as exc:
            raise NodeValidationError(str(exc)) from exc

        return self._sql_code_metadata

    @on_validation
    def validate_sql_code(self) -> None:
        """Валидирует SQL без попытки понять его бизнес-семантику."""
        if not self.should_validate_sql_code():
            return
        self.ensure_sql_code_metadata()
