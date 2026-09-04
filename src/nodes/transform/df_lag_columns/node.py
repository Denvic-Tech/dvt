from typing import List

import dask.dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO


class DataFrameLagColumns(DFOutputBaseNode):
    TITLE = "Lag Columns (сдвиг значений по строке)"
    EMOJI = "⏪"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()

    columns_to_lag: List[IO.COLUMN_NAME] = InputField(
        description="Колонки для создания лагов"
    )

    lag_steps: IO.INT = InputField(
        description='Количество шагов сдвига (положительное - сдвиг вниз, отрицательное - вверх)'
    )

    fill_value: IO.PRIMITIVE = InputField(
        default=None,
        description="Значение для заполнения пустых мест после сдвига (по умолчанию NaN)"
    )

    output: dd.DataFrame = OutputField()

    @on_validation
    def validate_lag_steps(self):
        if self.lag_steps == 0:
            raise ValueError("Количество шагов сдвига не может быть равно 0")

        # Проверяем, что указанные колонки существуют
        existing_columns = [col for col in self.columns_to_lag if col in self.df.columns]
        if not existing_columns:
            raise ValueError("Указанные колонки не найдены в DataFrame")

    def process(self):
        if not self.columns_to_lag:
            raise ValueError("Нет колонок для создания лагов")

        result_df = self.df.copy()

        for column in self.columns_to_lag:
            original_dtype = self.df[column].dtype

            lag_sign = '-' if self.lag_steps < 0 else ''
            new_column_name = f"{column}_lag{lag_sign}{abs(self.lag_steps)}"

            shifted_series = result_df[column].shift(periods=self.lag_steps)

            if self.fill_value is not None:
                shifted_series = shifted_series.fillna(self.fill_value)

            try:
                # Принудительно возвращаем исходный тип, чтоб не было конфликта
                result_df[new_column_name] = shifted_series.astype(original_dtype)
            except Exception:
                # Если привести к исходному не вышло (например, из-за NaN в строках),
                # приводим к object, но PyArrow все равно может капризничать,
                # поэтому для строк лучше fillna('')
                result_df[new_column_name] = shifted_series

        self.output = result_df
        return self.output