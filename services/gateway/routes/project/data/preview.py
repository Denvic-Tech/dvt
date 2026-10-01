"""JSON presentation of cached data; never modify the execution DataFrame."""

import orjson
import pandas as pd
import pyarrow as pa


def _preview_value(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binary: {len(value)} bytes>"
    if isinstance(value, dict):
        return {key: _preview_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_preview_value(item) for item in value]
    return value


def dataframe_preview_values(frame: pd.DataFrame) -> list[list]:
    preview = frame.copy(deep=False)
    for index, dtype in enumerate(frame.dtypes):
        arrow = dtype.pyarrow_dtype if isinstance(dtype, pd.ArrowDtype) else None
        if arrow is not None and (
            pa.types.is_binary(arrow)
            or pa.types.is_large_binary(arrow)
            or pa.types.is_fixed_size_binary(arrow)
            or pa.types.is_nested(arrow)
        ):
            # Construct an object column only in the presentation copy. pandas' JSON writer
            # otherwise tries to decode binary values as UTF-8, including nested headers.
            preview.isetitem(index, pd.Series(
                [_preview_value(value) for value in frame.iloc[:, index]],
                index=frame.index,
                dtype=object,
            ))
    return orjson.loads(
        preview.to_json(orient="split", date_format="iso", default_handler=str)
    ).get("data", [])
