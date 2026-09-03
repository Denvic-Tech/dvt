import pandas as pd
import numpy as np
import dask.dataframe as dd
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFrameReplaceValues(DFOutputBaseNode):
    TITLE = "Replace values"
    EMOJI = "🔃"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    column_to_replace: IO.COLUMN_NAME = InputField()
    dictionary: dict = InputField()

    output: dd.DataFrame = OutputField()

    def process(self):
        df = self.df
        col = self.column_to_replace
        col_dtype = df[col].dtype

        is_datetime = pd.api.types.is_datetime64_any_dtype(col_dtype)
        is_integer = pd.api.types.is_integer_dtype(col_dtype)
        is_float = pd.api.types.is_float_dtype(col_dtype)

        prepared_dict = {}
        output_dtype = col_dtype
        force_str = False

        null_aliases = {'null', 'none', 'nan', 'nil', ''}

        def prepare_val(v, target_type):
            nonlocal force_str, output_dtype

            if isinstance(v, str) and v.strip().lower() in null_aliases:
                return pd.NA

            if target_type == 'datetime':
                try:
                    ts_v = pd.to_datetime(v)
                    target_tz = getattr(col_dtype, 'tz', None)

                    if target_tz:
                        return ts_v.tz_localize(target_tz) if ts_v.tz is None else ts_v.tz_convert(target_tz)

                    return ts_v.tz_localize(None) if ts_v.tz else ts_v

                except:
                    force_str = True
                    output_dtype = pd.StringDtype()
                    return str(v)

            elif target_type == 'int':
                try:
                    return int(float(v))
                except:
                    force_str = True
                    output_dtype = pd.StringDtype()
                    return str(v)

            elif target_type == 'float':
                try:
                    return float(v)
                except:
                    force_str = True
                    output_dtype = pd.StringDtype()
                    return str(v)

            return v

        for k, v in self.dictionary.items():

            if isinstance(k, str) and k.lower() in null_aliases:
                prepared_dict[pd.NA] = prepare_val(
                    v,
                    'datetime' if is_datetime else (
                        'int' if is_integer else 'float' if is_float else 'str'
                    )
                )
                continue

            try:
                if is_datetime:
                    ts_key = pd.to_datetime(k)
                    target_tz = getattr(col_dtype, 'tz', None)
                    val = prepare_val(v, 'datetime')

                    if target_tz:
                        if ts_key.tz is None:
                            prepared_dict[ts_key.tz_localize(target_tz)] = val
                            prepared_dict[ts_key.tz_localize('UTC').tz_convert(target_tz)] = val
                        else:
                            prepared_dict[ts_key.tz_convert(target_tz)] = val
                    else:
                        prepared_dict[ts_key.tz_localize(None) if ts_key.tz else ts_key] = val

                elif is_integer:
                    prepared_dict[int(float(k))] = prepare_val(v, 'int')

                elif is_float:
                    prepared_dict[float(k)] = prepare_val(v, 'float')

                else:
                    prepared_dict[str(k)] = str(v)
            except:
                prepared_dict[k] = v

        def apply_replace(series, mapping, do_force_str):
            series = series.astype(series.dtype).where(series.notna(), pd.NA)

            if do_force_str:
                s_str = series.astype(pd.StringDtype())
                m_str = {str(k): str(v) for k, v in mapping.items()}

                result = s_str.map(m_str)
                return result.fillna(s_str)

            mask = series.isin(mapping.keys())

            result = series.where(~mask, series.map(mapping))

            if pd.NA in mapping:
                result = result.where(~series.isna(), mapping[pd.NA])

            return result

        new_col = df[col].map_partitions(
            apply_replace,
            prepared_dict,
            force_str,
            meta=(col, output_dtype)
        )

        self.output = df.assign(**{col: new_col})
