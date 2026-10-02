from typing import Optional

from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_mixins.column_rules import ColumnRulesMixin
from src.node_dsl.node_typing import IO
from src.nodes.transform._shared.column_rules import OPERATIONS


class DataFrameRegexReplace(ColumnRulesMixin, DFOutputBaseNode):
    """
    Заменяет значения в выбранной колонке на основе регулярного выражения.
    Для каждой строки применяется re.sub(pattern, replacement, string).
    """

    COLUMN_RULE_OPERATION = OPERATIONS["regex"]
    LEGACY_RULE_INPUTS = ("column_to_replace", "pattern", "replacement",)
    LEGACY_REQUIRED = ("column_to_replace", "pattern",)

    TITLE = "Regex Replace"
    ICON_KEY = "dataframe-regex-replace"
    EMOJI = "✍️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Inspect the chosen field and required null behavior; the node stringifies its values "
            "before regex replacement."
        ),
    )
    column_to_replace: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Choose an existing field to update in place. The result is string data, so do not "
            "expect numeric or datetime dtype preservation."
        ),
        description="Колонка для замены значений"
    )
    pattern: str | None = InputField(
        agent_description=(
            "Supply a valid regular expression and test it against representative matches and "
            "non-matches. Escape literal metacharacters when matching text literally."
        ),
        description="Регулярное выражение для поиска"
    )
    replacement: Optional[str] = InputField(
        agent_description=(
            "Use a string replacement, with the regex engine's supported group references if "
            "needed. The default empty string removes matches; avoid null because the underlying "
            "replacement operation expects a string or callable."
        ),default='',
        description="Строка для замены найденного совпадения"
    )

    output: dd.DataFrame = OutputField()

    def process_legacy(self):
        """Основной метод обработки"""
        # Применяем regex replace на Dask DataFrame
        self.output = self.df.assign(
            **{
                self.column_to_replace: self.df[self.column_to_replace]
                .astype(str)
                .str.replace(self.pattern, self.replacement, regex=True)
            }
        )
