from collections.abc import Iterable, Mapping
from dataclasses import replace

from dask import dataframe as dd

from core.types.dataframe_index import PhysicalDataFrameIndex

_INDEX_DESCRIPTOR_ATTR = "_dvt_physical_index"


def available_index_name(base: str, columns: Iterable[object]) -> str:
    occupied = {str(column).strip().lower() for column in columns}
    candidate = base
    suffix = 1
    while candidate in occupied:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def set_physical_index(
    frame: dd.DataFrame, descriptor: PhysicalDataFrameIndex | None
) -> dd.DataFrame:
    if descriptor is not None and frame.index.name == descriptor.name:
        object.__setattr__(frame, _INDEX_DESCRIPTOR_ATTR, (frame.expr, descriptor))
    return frame


def get_physical_index(frame: dd.DataFrame) -> PhysicalDataFrameIndex | None:
    # Read the collection's own state. Dask resolves unknown attributes as column names.
    entry = vars(frame).get(_INDEX_DESCRIPTOR_ATTR)
    if entry is None or entry[0] is not frame.expr:
        return None
    return entry[1]


def carry_physical_index(
    source: dd.DataFrame,
    result: dd.DataFrame,
    *,
    rename: Mapping[str, str] | None = None,
) -> dd.DataFrame:
    descriptor = get_physical_index(source)
    if descriptor is None:
        return result
    bound = descriptor.bound_column
    if rename and bound is not None:
        bound = rename.get(bound, bound)
    name = descriptor.name
    if result.index.name == name and name in result.columns:
        name = available_index_name(name, result.columns)
        result = result.rename_axis(name)
    return set_physical_index(
        result,
        replace(
            descriptor,
            name=name,
            bound_column=bound if list(result.columns).count(bound) == 1 else None,
        ),
    )
