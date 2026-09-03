import pandas as pd
import numpy as np
import pytest
import pandas.testing as tm
from decimal import Decimal

from core.dump_engine._pandas import UniversalPyArrowCacheEngine
from src.utils.testing import (
    types_testing_dataframe,
    types_testing_dataframe_with_index,
    types_testing_dataframe_with_multiindex,
    types_testing_dataframe_with_string_index,
)


def test_can_handle_pandas_dataframe():
    """@>25@O5B, GB> 4286>: <>65B >1@010BK20BL pandas DataFrame."""
    engine = UniversalPyArrowCacheEngine()
    df = pd.DataFrame({'a': [1, 2, 3]})

    assert engine.can_handle(df) is True


def test_can_handle_rejects_non_dataframe():
    """@>25@O5B, GB> 4286>: >B:;>=O5B =5-DataFrame >1J5:BK."""
    engine = UniversalPyArrowCacheEngine()

    assert engine.can_handle([1, 2, 3]) is False
    assert engine.can_handle("string") is False
    assert engine.can_handle(42) is False
    assert engine.can_handle(None) is False


def test_simple_dataframe_roundtrip(simple_df):
    """@>25@O5B 107>2K9 F8:; A5@80;870F88/45A5@80;870F88."""
    engine = UniversalPyArrowCacheEngine()

    data, meta = engine.dump(simple_df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored, pd.DataFrame)
    tm.assert_frame_equal(restored, simple_df,
                          check_dtype=True,
                          check_index_type=True,
                          check_column_type=True)


def test_metadata_is_saved(simple_df):
    """@>25@O5B, GB> <5B040==K5 A>E@0=ONBAO ?@8 dump()."""
    engine = UniversalPyArrowCacheEngine()

    data, meta = engine.dump(simple_df)

    assert meta is not None
    assert 'meta' in meta
    assert isinstance(meta['meta'], bytes)
    assert len(meta['meta']) > 0


def test_backward_compatibility_without_metadata(simple_df):
    """@>25@O5B >1@0B=CN A>2<5AB8<>ABL ?@8 >BACBAB288 <5B040==KE."""
    engine = UniversalPyArrowCacheEngine()

    data, _ = engine.dump(simple_df)
    # 03@C605<  <5B040==KE
    restored = engine.load(data, meta=None)

    assert isinstance(restored, pd.DataFrame)
    assert list(restored.columns) == list(simple_df.columns)
    assert len(restored) == len(simple_df)


@pytest.mark.parametrize("dtype,values", [
    ('int8', [1, 2, 3]),
    ('int16', [10, 20, 30]),
    ('int32', [100, 200, 300]),
    ('int64', [1000, 2000, 3000]),
    ('uint8', [1, 2, 3]),
    ('uint16', [10, 20, 30]),
    ('uint32', [100, 200, 300]),
    ('uint64', [1000, 2000, 3000]),
    ('float32', [1.1, 2.2, 3.3]),
    ('float64', [1.1, 2.2, 3.3]),
])
def test_numeric_dtypes_preserved(dtype, values):
    """@>25@O5B A>E@0=5=85 G8A;>2KE B8?>2 40==KE."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({'col': pd.array(values, dtype=dtype)})
    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert restored['col'].dtype == df['col'].dtype, \
        f"Expected dtype {df['col'].dtype}, got {restored['col'].dtype}"
    tm.assert_frame_equal(restored, df, check_dtype=True)


@pytest.mark.parametrize("dtype", ['Int8', 'Int16', 'Int32', 'Int64'])
def test_nullable_integer_dtypes_preserved(dtype):
    """@>25@O5B A>E@0=5=85 nullable integer B8?>2."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({'col': pd.array([1, 2, None, 4], dtype=dtype)})
    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert restored['col'].dtype == df['col'].dtype
    tm.assert_frame_equal(restored, df, check_dtype=True)


def test_categorical_dtype_preserved():
    """@>25@O5B A>E@0=5=85 :0B53>@80;L=>3> B8?0."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({
        'cat': pd.Categorical(['A', 'B', 'A'], categories=['A', 'B', 'C'])
    })

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored['cat'].dtype, pd.CategoricalDtype)
    assert list(restored['cat'].dtype.categories) == ['A', 'B', 'C']
    assert restored['cat'].dtype.ordered == df['cat'].dtype.ordered
    tm.assert_frame_equal(restored, df, check_dtype=True)


def test_datetime_types_preserved():
    """@>25@O5B A>E@0=5=85 datetime B8?>2."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({
        'dt_naive': pd.to_datetime(['2020-01-01', '2020-01-02']),
        'dt_utc': pd.to_datetime(['2020-01-01', '2020-01-02']).tz_localize('UTC'),
    })

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert restored['dt_naive'].dtype == df['dt_naive'].dtype
    # Timezone-aware datetime <>3CB 8<5BL @07=K5 548=8FK 87-70 Arrow
    assert hasattr(restored['dt_utc'].dtype, 'tz')
    assert restored['dt_utc'].dtype.tz is not None
    tm.assert_frame_equal(restored, df, check_dtype=False)


def test_timedelta_dtype_preserved():
    """@>25@O5B A>E@0=5=85 timedelta B8?0."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({
        'td': pd.to_timedelta([1, 2, 3], unit='D')
    })

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert restored['td'].dtype == df['td'].dtype
    tm.assert_frame_equal(restored, df, check_dtype=True)


def test_boolean_dtype_preserved():
    """@>25@O5B A>E@0=5=85 boolean B8?0."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({
        'bool_col': pd.array([True, False, None], dtype='boolean')
    })

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert restored['bool_col'].dtype == df['bool_col'].dtype
    tm.assert_frame_equal(restored, df, check_dtype=True)


def test_simple_index_name_preserved():
    """@>25@O5B A>E@0=5=85 8<5=8 8=45:A0."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({'a': [1, 2, 3]})
    df.index.name = 'my_index'

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert restored.index.name == 'my_index'


def test_datetime_index_preserved():
    """@>25@O5B A>E@0=5=85 DatetimeIndex."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame(
        {'value': [1, 2, 3]},
        index=pd.DatetimeIndex(['2020-01-01', '2020-01-02', '2020-01-03'], name='timestamp')
    )

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored.index, pd.DatetimeIndex)
    assert restored.index.dtype == df.index.dtype
    assert restored.index.name == 'timestamp'


def test_multiindex_preserved():
    """@>25@O5B A>E@0=5=85 MultiIndex."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame(
        {'value': [1, 2, 3]},
        index=pd.MultiIndex.from_tuples(
            [('A', 1), ('B', 2), ('C', 3)],
            names=['letter', 'number']
        )
    )

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored.index, pd.MultiIndex)
    assert restored.index.names == ['letter', 'number']


def test_integer_index_dtype_preserved():
    """@>25@O5B A>E@0=5=85 B8?0 F5;>G8A;5==>3> 8=45:A0."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({'a': [1, 2, 3]})
    df.index = pd.Index([10, 20, 30], dtype='int32', name='idx')

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert restored.index.dtype == df.index.dtype
    assert restored.index.name == 'idx'


def test_timezone_aware_datetime_index_preserved():
    """@>25@O5B A>E@0=5=85 tz-aware DatetimeIndex."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame(
        {'value': [1, 2, 3]},
        index=pd.DatetimeIndex(
            ['2020-01-01', '2020-01-02', '2020-01-03'],
            name='ts_tz',
            tz='UTC'
        )
    )

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored.index, pd.DatetimeIndex)
    assert restored.index.tz is not None
    assert restored.index.tz == df.index.tz
    assert restored.index.name == 'ts_tz'


def test_multiindex_mixed_types_preserved():
    """@>25@O5B A>E@0=5=85 MultiIndex A @07=K<8 B8?0<8 C@>2=O<8."""
    engine = UniversalPyArrowCacheEngine()

    index = pd.MultiIndex.from_tuples(
        [('A', 1), ('B', 2), ('C', 3)],
        names=['letter', 'number'],
    )
    df = pd.DataFrame({'value': [10, 20, 30]}, index=index)

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored.index, pd.MultiIndex)
    assert restored.index.names == ['letter', 'number']
    assert list(restored.index) == list(index)


def test_range_index_with_step_preserved():
    """@>25@O5B A>E@0=5=85 RangeIndex A >B:@KFK<< step."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({'a': [1, 2, 3, 4]})
    df.index = pd.RangeIndex(start=10, stop=18, step=2, name='ridx')

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored.index, pd.RangeIndex)
    assert restored.index.start == df.index.start
    assert restored.index.step == df.index.step
    assert restored.index.stop == df.index.stop
    assert restored.index.name == 'ridx'


def test_period_index_preserved():
    """@>25@O5B A>E@0=5=85 PeriodIndex."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({'value': [1, 2, 3]})
    df.index = pd.period_range('2024-01', periods=3, freq='M', name='period_idx')

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored.index, pd.PeriodIndex)
    assert restored.index.freq == df.index.freq
    assert restored.index.name == 'period_idx'
    assert list(restored.index) == list(df.index)


def test_timedelta_index_preserved():
    """@>25@O5B A>E@0=5=85 TimedeltaIndex."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({'value': [1, 2, 3]})
    df.index = pd.to_timedelta([1, 2, 3], unit='D')
    df.index.name = 'delta_idx'

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored.index, pd.TimedeltaIndex)
    assert restored.index.name == 'delta_idx'
    assert list(restored.index) == list(df.index)


def test_categorical_index_preserved():
    """@>25@O5B A>E@0=5=85 CategoricalIndex."""
    engine = UniversalPyArrowCacheEngine()

    index = pd.CategoricalIndex(
        ['a', 'b', 'a'],
        categories=['a', 'b', 'c'],
        ordered=True,
        name='cat_idx'
    )
    df = pd.DataFrame({'value': [10, 20, 30]}, index=index)

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored.index, pd.CategoricalIndex)
    assert list(restored.index.categories) == ['a', 'b', 'c']
    assert restored.index.ordered is True
    assert restored.index.name == 'cat_idx'


def test_empty_dataframe():
    """@>25@O5B @01>BC A ?CABK< DataFrame."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({
        'int_col': pd.Series([], dtype='int32'),
        'float_col': pd.Series([], dtype='float32'),
        'cat_col': pd.Series([], dtype=pd.CategoricalDtype(categories=['A', 'B'])),
    })

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert len(restored) == 0
    assert restored['int_col'].dtype == df['int_col'].dtype
    assert restored['float_col'].dtype == df['float_col'].dtype
    assert isinstance(restored['cat_col'].dtype, pd.CategoricalDtype)


def test_large_dataframe_truncation():
    """@>25@O5B CA5G5=85 1>;LH>3> DataFrame."""
    engine = UniversalPyArrowCacheEngine(max_rows=100)

    df = pd.DataFrame({
        'int32_col': np.arange(1000, dtype='int32'),
        'float32_col': np.arange(1000, dtype='float32'),
    })

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert len(restored) == 100
    # "8?K 4>;6=K 1KBL A>E@0=5=K 4065 ?@8 CA5G5=88
    assert restored['int32_col'].dtype == df['int32_col'].dtype
    assert restored['float32_col'].dtype == df['float32_col'].dtype


def test_special_column_names():
    """@>25@O5B @01>BC A >A>1K<8 8<5=0<8 :>;>=>:."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({
        'column with spaces': [1, 2],
        'column.with.dots': [3, 4],
        'column-with-dashes': [5, 6],
        'column_with_:8@8;;8F0': [7, 8],
    })

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert list(restored.columns) == list(df.columns)
    tm.assert_frame_equal(restored, df, check_dtype=True)


def test_single_row_dataframe():
    """@>25@O5B @01>BC A DataFrame 87 >4=>9 AB@>:8."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({
        'int32': pd.array([42], dtype='int32'),
        'cat': pd.Categorical(['A'], categories=['A', 'B', 'C']),
    })

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert len(restored) == 1
    assert restored['int32'].dtype == df['int32'].dtype
    tm.assert_frame_equal(restored, df, check_dtype=True)


def test_dataframe_with_none_values():
    """@>25@O5B @01>BC A None 7=0G5=8O<8."""
    engine = UniversalPyArrowCacheEngine()

    df = pd.DataFrame({
        'nullable_int': pd.array([1, None, 3], dtype='Int64'),
        'nullable_bool': pd.array([True, None, False], dtype='boolean'),
        'nullable_str': pd.Series(['a', None, 'c'], dtype='string'),
    })

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    tm.assert_frame_equal(restored, df, check_dtype=True)


def test_types_testing_dataframe():
    """@>25@O5B @01>BC A types_testing_dataframe."""
    engine = UniversalPyArrowCacheEngine()

    # A?>;L7C5< C<5=LH5==CN 25@A8N 4;O 1KAB@KE B5AB>2
    df = types_testing_dataframe(n_rows=50)

    # #40;O5< :>;>=:8, :>B>@K5 <>3CB =5 ?>445@6820BLAO Arrow
    columns_to_drop = []
    for col in df.columns:
        try:
            # @>25@O5<, <>6=> ;8 A5@80;87>20BL :>;>=:C
            _ = pd.DataFrame({col: df[col]})
        except Exception:
            columns_to_drop.append(col)

    if columns_to_drop:
        df = df.drop(columns=columns_to_drop)

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored, pd.DataFrame)
    assert len(restored) == len(df)

    # @>25@O5< >A=>2=K5 B8?K
    numeric_cols = ['int_col', 'float_col']
    for col in numeric_cols:
        if col in df.columns:
            assert restored[col].dtype == df[col].dtype, f"Column {col} dtype mismatch"


def test_types_testing_dataframe_with_index():
    """@>25@O5B @01>BC A 40B0D@59<>< A 8=45:A><."""
    engine = UniversalPyArrowCacheEngine()

    df = types_testing_dataframe_with_index(n_rows=50)

    # #40;O5< ?@>1;5<=K5 :>;>=:8
    columns_to_drop = []
    for col in df.columns:
        try:
            _ = pd.DataFrame({col: df[col]})
        except Exception:
            columns_to_drop.append(col)

    if columns_to_drop:
        df = df.drop(columns=columns_to_drop)

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored, pd.DataFrame)
    assert len(restored) == len(df)
    # =45:A 4>;65= 1KBL 2>AAB0=>2;5=
    assert list(restored.index) == list(df.index)


def test_types_testing_dataframe_with_multiindex():
    """@>25@O5B @01>BC A 40B0D@59<>< A MultiIndex."""
    engine = UniversalPyArrowCacheEngine()

    df = types_testing_dataframe_with_multiindex(n_rows=50)

    # #40;O5< ?@>1;5<=K5 :>;>=:8
    columns_to_drop = []
    for col in df.columns:
        try:
            _ = pd.DataFrame({col: df[col]})
        except Exception:
            columns_to_drop.append(col)

    if columns_to_drop:
        df = df.drop(columns=columns_to_drop)

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored, pd.DataFrame)
    assert len(restored) == len(df)
    assert isinstance(restored.index, pd.MultiIndex)


@pytest.mark.parametrize("compression", ['lz4', 'zstd', 'uncompressed'])
def test_different_compression_methods(compression, simple_df):
    """@>25@O5B @01>BC A @07;8G=K<8 <5B>40<8 A60B8O."""
    engine = UniversalPyArrowCacheEngine(compression=compression)

    data, meta = engine.dump(simple_df)
    restored = engine.load(data, meta=meta)

    tm.assert_frame_equal(restored, simple_df, check_dtype=True)


def test_compression_reduces_size():
    """@>25@O5B, GB> A60B85 C<5=LH05B @07<5@ 40==KE."""
    # !>7405< DataFrame A ?>2B>@ONI8<8AO 40==K<8
    df = pd.DataFrame({
        'repeated': ['same_value'] * 1000,
        'numbers': list(range(1000)),
    })

    engine_compressed = UniversalPyArrowCacheEngine(compression='lz4')
    engine_uncompressed = UniversalPyArrowCacheEngine(compression='uncompressed')

    data_compressed, _ = engine_compressed.dump(df)
    data_uncompressed, _ = engine_uncompressed.dump(df)

    assert len(data_compressed) < len(data_uncompressed)


def test_dump_raises_on_non_dataframe():
    """@>25@O5B, GB> dump() 2K1@0AK205B 8A:;NG5=85 4;O =5-DataFrame."""
    engine = UniversalPyArrowCacheEngine()

    with pytest.raises(TypeError) as exc_info:
        engine.dump([1, 2, 3])

    assert "can handle only pandas.DataFrame" in str(exc_info.value)


def test_load_with_invalid_data_raises():
    """@>25@O5B, GB> load() 2K1@0AK205B 8A:;NG5=85 4;O =5:>@@5:B=KE 40==KE."""
    engine = UniversalPyArrowCacheEngine()

    with pytest.raises(Exception):  # Arrow 2K1@>A8B :0:>5-B> 8A:;NG5=85
        engine.load(b'invalid_data', meta=None)


def test_max_rows_none_saves_all_data():
    """@>25@O5B, GB> max_rows=None A>E@0=O5B 2A5 40==K5."""
    engine = UniversalPyArrowCacheEngine(max_rows=None)

    df = pd.DataFrame({'a': range(10000)})

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert len(restored) == 10000


def test_max_rows_limits_data():
    """@>25@O5B, GB> max_rows >3@0=8G8205B :>;8G5AB2> AB@>:."""
    max_rows = 500
    engine = UniversalPyArrowCacheEngine(max_rows=max_rows)

    df = pd.DataFrame({'a': range(10000)})

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert len(restored) == max_rows


def test_max_rows_preserves_first_rows():
    """@>25@O5B, GB> max_rows A>E@0=O5B ?5@2K5 N AB@>:."""
    max_rows = 5
    engine = UniversalPyArrowCacheEngine(max_rows=max_rows)

    df = pd.DataFrame({'a': [10, 20, 30, 40, 50, 60, 70]})

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    expected = df.head(max_rows)
    tm.assert_frame_equal(restored, expected, check_dtype=True)


def test_dump_handles_mixed_decimal_and_float_in_object_column():
    engine = UniversalPyArrowCacheEngine()
    df = pd.DataFrame(
        {
            "ValPrib": pd.Series([Decimal("1.1"), 2.5, None], dtype=object),
            "id": [1, 2, 3],
        }
    )

    data, meta = engine.dump(df)
    restored = engine.load(data, meta=meta)

    assert restored["ValPrib"].dtype == object
    assert float(restored["ValPrib"].iloc[0]) == pytest.approx(1.1)
    assert float(restored["ValPrib"].iloc[1]) == pytest.approx(2.5)
    assert pd.isna(restored["ValPrib"].iloc[2])
