from typing import Optional

from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFrameRegexReplace(DFOutputBaseNode):
    """
    Заменяет значения в выбранной колонке на основе регулярного выражения.
    Для каждой строки применяется re.sub(pattern, replacement, string).
    """
    TITLE = "Regex Replace"
    EMOJI = "✍️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    column_to_replace: IO.COLUMN_NAME = InputField(
        description="Колонка для замены значений"
    )
    pattern: str = InputField(
        description="Регулярное выражение для поиска"
    )
    replacement: Optional[str] = InputField(default='',
        description="Строка для замены найденного совпадения"
    )

    output: dd.DataFrame = OutputField()

    def process(self):
        """Основной метод обработки"""
        # Применяем regex replace на Dask DataFrame
        self.output = self.df.assign(
            **{
                self.column_to_replace: self.df[self.column_to_replace]
                .astype(str)
                .str.replace(self.pattern, self.replacement, regex=True)
            }
        )
