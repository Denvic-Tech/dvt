import dask.dataframe as dd
import numpy as np
import pandas as pd
import pytest
from pandas import StringDtype

from src.nodes.transform.df_replace_values import DataFrameReplaceValues
from src.pipeline.execution_mode import PipelineExecutionMode


@pytest.mark.asyncio
async def test_dataframe_replace_values_timestamp():
    """Тест замены значений в колонке с типом Timestamp (с учетом TZ и без)"""

    # 1. Готовим данные: колонка без пояса и колонка с поясом GMT+5
    df_raw = pd.DataFrame({
        'dt_no_tz': pd.to_datetime(['2023-01-01 10:00:00', '2023-01-02 10:00:00']),
        'dt_tz': pd.to_datetime(['2023-01-01 10:00:00', '2023-01-02 10:00:00']).tz_localize('Asia/Yekaterinburg')
    })
    ddf = dd.from_pandas(df_raw, npartitions=1)

    # --- СЦЕНАРИЙ 1: Замена в колонке БЕЗ таймзоны ---
    # Мы передаем строку в словаре, она должна превратиться в Timestamp для сравнения
    replace_dict_no_tz = {"2023-01-01 10:00:00": pd.Timestamp("2025-01-01 00:00:00")}

    node_no_tz = DataFrameReplaceValues(
        user_id="test", project_id="test", task_id="test", node_id="node_1",
        df=ddf,
        column_to_replace='dt_no_tz',
        dictionary=replace_dict_no_tz
    )

    await node_no_tz.execute(PipelineExecutionMode.FULL)
    res_no_tz = node_no_tz.output.compute()

    # Проверяем, что первая дата заменилась, а вторая осталась прежней
    assert res_no_tz['dt_no_tz'].iloc[0] == pd.Timestamp("2025-01-01 00:00:00")
    assert res_no_tz['dt_no_tz'].iloc[1] == pd.Timestamp("2023-01-02 10:00:00")

    # --- СЦЕНАРИЙ 2: Замена в колонке С таймзоной (Asia/Yekaterinburg, GMT+5) ---
    # В словаре передаем "наивную" строку. Нода должна локализовать её в +05:00, чтобы Match сработал.
    replace_dict_tz = {"2023-01-01 10:00:00": "REPLACED"}

    node_tz = DataFrameReplaceValues(
        user_id="test", project_id="test", task_id="test", node_id="node_2",
        df=ddf,
        column_to_replace='dt_tz',
        dictionary=replace_dict_tz
    )

    await node_tz.execute(PipelineExecutionMode.FULL)
    res_tz = node_tz.output.compute()

    # Проверяем успешную замену
    # Если локализация в коде ноды сработала верно, ключ "10:00:00" совпадет с объектом в DF
    assert res_tz['dt_tz'].iloc[0] == "REPLACED"
    # Так как мы заменили значение на строку, вся колонка стала строковой.
    # Приводим ожидаемый Timestamp к строке для сравнения.
    expected_val = str(pd.Timestamp("2023-01-02 10:00:00").tz_localize('Asia/Yekaterinburg'))
    assert res_tz['dt_tz'].iloc[1] == expected_val


@pytest.mark.asyncio
async def test_dataframe_replace_values_invalid_strings():
    """Тест того, что невалидные строки в словаре не ломают процесс (блок try-except)"""
    df_raw = pd.DataFrame({
        'dt': pd.to_datetime(['2023-01-01'])
    })
    ddf = dd.from_pandas(df_raw, npartitions=1)

    # 'not_a_date' не распарсится pd.to_datetime, сработает exception в коде ноды
    replace_dict = {"not_a_date": "value", "2023-01-01": pd.Timestamp("2024-01-01")}

    node = DataFrameReplaceValues(
        user_id="test", project_id="test", task_id="test", node_id="node_3",
        df=ddf,
        column_to_replace='dt',
        dictionary=replace_dict
    )

    await node.execute(PipelineExecutionMode.FULL)
    res = node.output.compute()

    assert res['dt'].iloc[0] == pd.Timestamp("2024-01-01")


@pytest.mark.asyncio
async def test_replace_values_utc_to_gmt5():
    # 1. Создаем DF c GMT+5 (Etc/GMT-5)
    # 2017-12-01 02:00:00 в GMT+5 == 2017-11-30 21:00:00 в UTC
    tz_name = "Etc/GMT-5"
    ts_val = pd.Timestamp("2017-12-01 02:00:00").tz_localize(tz_name)

    df_raw = pd.DataFrame({'YM': [ts_val]})
    ddf = dd.from_pandas(df_raw, npartitions=1)

    # 2. Словарь с ключом в UTC (как будто "наивная" строка)
    replace_dict = {
        "2017-11-30 21:00:00": "REPLACED_VAL"
    }

    node = DataFrameReplaceValues(
        user_id="u", project_id="p", task_id="t", node_id="n",
        df=ddf,
        column_to_replace='YM',
        dictionary=replace_dict
    )

    await node.execute(PipelineExecutionMode.FULL)
    res = node.output.compute()

    # Проверка
    print(f"\nOriginal: {ts_val}")
    print(f"Result:   {res['YM'].iloc[0]}")

    assert res['YM'].iloc[0] == "REPLACED_VAL"


@pytest.mark.asyncio
async def test_replace_values_floats():
    """Тест замены в float колонке"""
    df_raw = pd.DataFrame({'floats': [1.1, 2.5, 3.0]})
    ddf = dd.from_pandas(df_raw, npartitions=1)

    replace_dict = {
        "1.1": "one_point_one",  # Замена на строку
        "2.5": "two_point_five"
    }

    node = DataFrameReplaceValues(
        user_id="u", project_id="p", task_id="t", node_id="n",
        df=ddf,
        column_to_replace='floats',
        dictionary=replace_dict
    )

    await node.execute(PipelineExecutionMode.FULL)
    res = node.output.compute()

    # Проверяем значения
    assert res['floats'].iloc[0] == "one_point_one"
    # Проверяем, что dtype == StringDtype
    assert res['floats'].dtype == StringDtype(na_value=np.nan)


@pytest.mark.asyncio
async def test_replace_null_values():
    df_raw = pd.DataFrame({'val': [1, 2, None]}) # Последний - NaN
    ddf = dd.from_pandas(df_raw, npartitions=1)

    # Заменяем null на 999
    replace_dict = {"null": "999"}

    node = DataFrameReplaceValues(
        user_id="u", project_id="p", task_id="t", node_id="n",
        df=ddf, column_to_replace='val', dictionary=replace_dict
    )

    await node.execute(PipelineExecutionMode.FULL)
    res = node.output.compute()

    assert res['val'].iloc[2] == 999

@pytest.mark.asyncio
async def test_replace_value_to_null_empty_string():
    df_raw = pd.DataFrame({'val': [848, 100]})
    ddf = dd.from_pandas(df_raw, npartitions=1)

    replace_dict = {"848": ""}

    node = DataFrameReplaceValues(
        user_id="u", project_id="p", task_id="t", node_id="n",
        df=ddf,
        column_to_replace='val',
        dictionary=replace_dict
    )

    await node.execute(PipelineExecutionMode.FULL)
    res = node.output.compute()

    assert pd.isna(res['val'].iloc[0])
    assert res['val'].iloc[1] == 100

@pytest.mark.asyncio
async def test_replace_value_to_null_string_null():
    df_raw = pd.DataFrame({'val': [848, 200]})
    ddf = dd.from_pandas(df_raw, npartitions=1)

    replace_dict = {"848": "null"}

    node = DataFrameReplaceValues(
        user_id="u", project_id="p", task_id="t", node_id="n",
        df=ddf,
        column_to_replace='val',
        dictionary=replace_dict
    )

    await node.execute(PipelineExecutionMode.FULL)
    res = node.output.compute()

    assert pd.isna(res['val'].iloc[0])
    assert res['val'].iloc[1] == 200

@pytest.mark.asyncio
async def test_replace_value_to_null_with_spaces_and_case():
    df_raw = pd.DataFrame({'val': [848]})
    ddf = dd.from_pandas(df_raw, npartitions=1)

    replace_dict = {"848": "  NULL  "}

    node = DataFrameReplaceValues(
        user_id="u", project_id="p", task_id="t", node_id="n",
        df=ddf,
        column_to_replace='val',
        dictionary=replace_dict
    )

    await node.execute(PipelineExecutionMode.FULL)
    res = node.output.compute()

    assert pd.isna(res['val'].iloc[0])

@pytest.mark.asyncio
async def test_replace_float_value_to_null():
    df_raw = pd.DataFrame({'val': [848.5, 1.1]})
    ddf = dd.from_pandas(df_raw, npartitions=1)

    replace_dict = {"848.5": ""}

    node = DataFrameReplaceValues(
        user_id="u", project_id="p", task_id="t", node_id="n",
        df=ddf,
        column_to_replace='val',
        dictionary=replace_dict
    )

    await node.execute(PipelineExecutionMode.FULL)
    res = node.output.compute()

    assert pd.isna(res['val'].iloc[0])
    assert res['val'].iloc[1] == 1.1

@pytest.mark.asyncio
async def test_replace_datetime_to_null():
    df_raw = pd.DataFrame({
        'dt': pd.to_datetime(["2023-01-01", "2023-01-02"])
    })
    ddf = dd.from_pandas(df_raw, npartitions=1)

    replace_dict = {"2023-01-01": ""}

    node = DataFrameReplaceValues(
        user_id="u", project_id="p", task_id="t", node_id="n",
        df=ddf,
        column_to_replace='dt',
        dictionary=replace_dict
    )

    await node.execute(PipelineExecutionMode.FULL)
    res = node.output.compute()

    assert pd.isna(res['dt'].iloc[0])
    assert res['dt'].iloc[1] == pd.Timestamp("2023-01-02")
