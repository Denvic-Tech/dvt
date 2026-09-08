from typing import List, Optional

from dask import dataframe as dd
from pandas.core.dtypes.common import is_integer_dtype, is_float_dtype

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO


class DataFrameNumericNormalizer(DFOutputBaseNode):
    TITLE = "Normalize numeric columns DataFrames"
    EMOJI = "📏"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()

    columns_to_normalize: Optional[List[IO.COLUMN_NAME]] = InputField(
        description="Колонки для нормализации. Если пустые, то будут все колонки"
    )

    lower_border: IO.FLOAT = InputField(default=0, description='Нижняя граница нормализации')
    upper_border: IO.FLOAT = InputField(default=0, description='Верхняя граница нормализации')

    replace_empty_values: IO.BOOLEAN = InputField(default=True, description="Заполнять ли NaN/null значения")

    output: dd.DataFrame = OutputField()

    @on_validation
    def validate_borders(self):
        if self.lower_border > self.upper_border:
            raise ValueError("Нижняя граница не может быть больше верхней границы")

    def process(self):
        if self.columns_to_normalize:
            columns_to_check = [
                col for col in self.columns_to_normalize
                if col in self.df.columns
            ]
        else:
            columns_to_check = self.df.columns.tolist()

        # Фильтруем только те колонки, которые можно сравнивать с числами
        numeric_columns = []
        for column in columns_to_check:
            dtype = self.df[column].dtype

            # Проверяем, что это число И не timedelta/complex
            if is_integer_dtype(dtype) or is_float_dtype(dtype):
                numeric_columns.append(column)

        if not numeric_columns:
            raise ValueError("Нет подходящих числовых колонок для нормализации")

        result_df = self.df.copy()
        for column in numeric_columns:
            result_df[column] = result_df[column].clip(
                lower=self.lower_border,
                upper=self.upper_border
            )

            if self.replace_empty_values:
                result_df[column] = result_df[column].fillna(self.lower_border)
        self.output = result_df
        return self.output

