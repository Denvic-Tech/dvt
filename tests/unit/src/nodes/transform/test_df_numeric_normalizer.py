import dask.dataframe as dd
import numpy as np
import pandas as pd
import pytest

from src.nodes.transform.df_numeric_normalizer import DataFrameNumericNormalizer
from src.pipeline.execution_mode import PipelineExecutionMode


@pytest.mark.asyncio
async def test_dataframe_numeric_normalizer_with_specific_columns():
    """Тест нормализатора с выбранными колонками"""
    # Создаем датафрейм с разными значениями
    df = pd.DataFrame({
        'age': [-10, 0, 25, 150, 200],  # Выходят за границы
        'salary': [500, 1000, 1500, 2000, 2500],  # В пределах
        'name': ['Alice', 'Bob', 'Charlie', 'Dave', 'Eve'],  # Строковая колонка
        'score': [-50, -25, 0, 25, 50],  # Выбранная для нормализации
        'is_active': [True, False, True, True, False],  # Булевая колонка
    })

    ddf = dd.from_pandas(df, npartitions=1)

    # Создаем ноду и настраиваем
    node = DataFrameNumericNormalizer(user_id="user",
                                      project_id="project",
                                      task_id="task",
                                      node_id="node-normalize",
                                      df=ddf,
                                      columns_to_normalize=['age', 'score', 'is_active'],
                                      lower_border=0,
                                      upper_border=100)
    # Выполняем нормализацию
    await node.execute(PipelineExecutionMode.FULL)
    result_df = node.output.compute()

    # Проверяем результаты
    # Колонка age: -10 -> 0, 0 -> 0, 25 -> 25, 150 -> 100, 200 -> 100
    expected_age = [0, 0, 25, 100, 100]
    pd.testing.assert_series_equal(result_df['age'], pd.Series(expected_age, name='age'))

    # Колонка score: -50 -> 0, -25 -> 0, 0 -> 0, 25 -> 25, 50 -> 50
    expected_score = [0, 0, 0, 25, 50]
    pd.testing.assert_series_equal(result_df['score'], pd.Series(expected_score, name='score'))

    # Колонка salary не должна измениться (не выбрана для нормализации)
    pd.testing.assert_series_equal(result_df['salary'], df['salary'], check_dtype=False)

    # Колонка name не должна измениться (не числовая)
    pd.testing.assert_series_equal(result_df['name'], df['name'], check_dtype=False)

    # Колонка is_active не должна измениться (bool)
    pd.testing.assert_series_equal(result_df['is_active'], df['is_active'], check_dtype=False)

    # Проверяем, что не было создано лишних колонок
    assert set(result_df.columns) == set(df.columns)


@pytest.mark.asyncio
async def test_dataframe_numeric_normalizer_with_all_columns(types_test_dataframe):
    """Тест нормализатора со всеми колонками (автовыбор числовых)"""
    # Создаем dask DataFrame из фикстуры
    df = types_test_dataframe.copy()
    ddf = dd.from_pandas(df, npartitions=1)

    # Создаем ноду и настраиваем
    node = DataFrameNumericNormalizer(user_id="user",
                                      project_id="project",
                                      task_id="task",
                                      node_id="node-normalize",
                                      df=ddf,
                                      lower_border=10,
                                      upper_border=90)

    # Выполняем нормализацию
    await node.execute(PipelineExecutionMode.FULL)
    result_df = node.output.compute()

    # Проверяем, что нормализовались только числовые колонки
    numeric_columns = ['int_col', 'float_col', 'int_with_null', 'float_with_null']

    for col in numeric_columns:
        if col in df.columns:
            original_values = df[col]
            normalized_values = result_df[col]

            # Проверяем, что значения ограничены границами
            assert normalized_values.min() >= 10, f"Column {col}: min value {normalized_values.min()} < 10"
            assert normalized_values.max() <= 90, f"Column {col}: max value {normalized_values.max()} > 90"

            # Проверяем логику ограничения
            for orig, norm in zip(original_values, normalized_values):
                if pd.isna(orig):
                    assert norm == 10, f"Column {col}: {orig} should be clipped to 10, got {norm}"
                elif orig < 10:
                    assert norm == 10, f"Column {col}: {orig} should be clipped to 10, got {norm}"
                elif orig > 90:
                    assert norm == 90, f"Column {col}: {orig} should be clipped to 90, got {norm}"
                else:
                    # В пределах границ значения не меняются
                    assert norm == orig, f"Column {col}: {orig} should stay {orig}, got {norm}"

    # Проверяем, что нечисловые колонки не изменились
    non_numeric_columns = ['bool_col', 'str_col', 'cat_col', 'string_col', 'datetime_col',
                           'name', 'period_col']

    for col in non_numeric_columns:
        if col in df.columns and col in result_df.columns:
            pd.testing.assert_series_equal(
                result_df[col],
                df[col],
                check_dtype=False  # Dask может менять типы
            )

    # Проверяем, что сложные числовые типы (complex) не обрабатывались
    if 'complex_col' in result_df.columns:
        # complex колонка не должна была измениться
        pd.testing.assert_series_equal(
            result_df['complex_col'],
            df['complex_col'],
            check_dtype=False
        )


@pytest.mark.asyncio
async def test_dataframe_numeric_normalizer_nan_replacement():
    """Простой тест замены NaN значений"""
    df = pd.DataFrame({
        'col1': [1, np.nan, 3, np.nan, 5],
        'col2': [np.nan, 20, 30, np.nan, 50],
        'text': ['a', 'b', 'c', 'd', 'e']
    })

    ddf = dd.from_pandas(df, npartitions=1)

    # С заменой NaN
    node = DataFrameNumericNormalizer(user_id="user",
                                      project_id="project",
                                      task_id="task",
                                      node_id="node-normalize",
                                      df=ddf,
                                      columns_to_normalize=None,
                                      lower_border=10,
                                      upper_border=100,
                                      replace_empty_values=True)

    await node.execute(PipelineExecutionMode.FULL)
    result = node.output.compute()

    # Проверяем, что NaN заменены на lower_border (10)
    assert not result['col1'].isna().any()
    assert not result['col2'].isna().any()

    # Проверяем конкретные значения
    assert result.loc[1, 'col1'] == 10  # Было NaN → стало 10
    assert result.loc[3, 'col1'] == 10  # Было NaN → стало 10
    assert result.loc[0, 'col2'] == 10  # Было NaN → стало 10
    assert result.loc[3, 'col2'] == 10  # Было NaN → стало 10
    # Проверяем, что ненулевые значения ограничены границами
    assert result.loc[0, 'col1'] == 10  # 1 → 10 (ограничение снизу)
    assert result.loc[2, 'col2'] == 30  # 3 → 30 (clip не применялся)
    assert result.loc[4, 'col2'] == 50  # 5 → 50
