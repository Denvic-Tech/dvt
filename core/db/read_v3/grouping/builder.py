from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from core.db.read_v3.grouping.models import PartitionSegment, ValueKind
from core.db.read_v3.grouping.spec import GroupingSpec, GroupingSpecError
from core.db.read_v3.grouping.temporal import advance_granularity, floor_to_granularity
from core.db.read_v3.grouping.utils import pack_segments


def _resolve_bins(npartitions: Optional[int], total_rows: Optional[int]) -> int:
    if npartitions and npartitions > 0:
        return npartitions
    if total_rows and total_rows > 0:
        return max(1, min(64, math.ceil(total_rows / 100_000)))
    return 1


def _normalize_ranges(ranges: list[object] | tuple[object, ...]) -> list[tuple[object, object, bool]]:
    normalized: list[tuple[object, object, bool]] = []
    for item in ranges:
        if isinstance(item, dict):
            if "start" not in item or "end" not in item:
                raise GroupingSpecError("range item must include start and end")
            start = item.get("start")
            end = item.get("end")
            include_end = bool(item.get("include_end", False))
        elif isinstance(item, (list, tuple)):
            if len(item) < 2:
                raise GroupingSpecError("range item must have at least 2 elements")
            start = item[0]
            end = item[1]
            include_end = bool(item[2]) if len(item) > 2 else False
        else:
            raise GroupingSpecError("range item must be a dict or list")
        normalized.append((start, end, include_end))
    return normalized


def _normalize_percentiles(values: list[object] | tuple[object, ...]) -> list[float]:
    percentiles: list[float] = []
    for value in values:
        if not isinstance(value, (int, float)):
            raise GroupingSpecError("percentiles must be numbers")
        as_float = float(value)
        if as_float <= 0.0 or as_float >= 1.0:
            raise GroupingSpecError("percentiles must be between 0 and 1 (exclusive)")
        percentiles.append(as_float)
    return sorted(set(percentiles))


def _normalize_bool_values(values: list[object] | tuple[object, ...]) -> list[bool | None]:
    normalized: list[bool | None] = []
    for value in values:
        if value is None:
            normalized.append(None)
        elif isinstance(value, bool):
            normalized.append(value)
        elif isinstance(value, (int, float)) and value in (0, 1):
            normalized.append(bool(value))
        elif isinstance(value, str):
            key = value.strip().lower()
            if key in ("true", "1", "yes"):
                normalized.append(True)
            elif key in ("false", "0", "no"):
                normalized.append(False)
            elif key in ("null", "none"):
                normalized.append(None)
            else:
                raise GroupingSpecError(f"unsupported bool value: {value}")
        else:
            raise GroupingSpecError(f"unsupported bool value: {value}")
    return normalized


def build_custom_segments(
    *,
    helper,
    column_expr: str,
    column_name: str,
    value_kind: ValueKind,
    spec: GroupingSpec,
    total_rows: Optional[int],
    npartitions: Optional[int],
    limit: Optional[int],
    partition_granularity: Optional[str],
) -> list[PartitionSegment]:
    mode = spec.mode
    params = spec.params
    effective_total = None
    if total_rows is not None:
        effective_total = min(total_rows, limit) if limit is not None else total_rows

    if total_rows is None and hasattr(helper, "total_rows_expr"):
        total_rows = helper.total_rows_expr()
        effective_total = min(total_rows, limit) if limit is not None else total_rows

    bins = _resolve_bins(npartitions, total_rows)

    if value_kind in (ValueKind.DATE, ValueKind.DATETIME):
        return _build_date_segments(
            helper,
            column_expr,
            mode,
            params,
            effective_total,
            bins,
            partition_granularity,
        )
    if value_kind == ValueKind.STRING:
        return _build_string_segments(
            helper,
            column_expr,
            column_name,
            mode,
            params,
            effective_total,
            bins,
        )
    if value_kind == ValueKind.NUMERIC:
        return _build_numeric_segments(
            helper,
            column_expr,
            column_name,
            mode,
            params,
            effective_total,
            bins,
        )
    if value_kind == ValueKind.BOOL:
        return _build_bool_segments(helper, column_expr, mode, params, effective_total)
    raise GroupingSpecError(f"unsupported value kind for custom grouping: {value_kind.value}")


def _build_string_segments(
    helper,
    column_expr: str,
    column_name: str,
    mode: str,
    params: dict,
    total_rows: Optional[int],
    bins: int,
) -> list[PartitionSegment]:
    if mode in ("as_is", "as-is"):
        max_groups = params.get("max_groups")
        if max_groups is None and bins:
            max_groups = max(bins * 4, bins)
        counts = helper.value_counts_expr(column_expr, max_groups=max_groups)
        segments: list[PartitionSegment] = []
        collected = []
        total_seen = 0
        for value, count in counts:
            total_seen += count
            if value is None:
                segments.append(PartitionSegment(label="__null__", is_null=True, count=count))
            else:
                collected.append(value)
                segments.append(
                    PartitionSegment(label=str(value), include_values=[value], count=count)
                )
        if params.get("other", True):
            if total_rows is not None and total_rows > total_seen:
                other_count = total_rows - total_seen
            else:
                if collected:
                    predicate = (
                        f"{column_expr} NOT IN ({helper.render_in_list(collected)}) "
                        f"AND {column_expr} IS NOT NULL"
                    )
                else:
                    predicate = f"{column_expr} IS NOT NULL"
                other_count = helper.count_predicate(predicate)
            if other_count:
                segments.append(
                    PartitionSegment(
                        label="__other__",
                        exclude_values=collected,
                        count=other_count,
                    )
                )
        return pack_segments(segments, bins=bins)

    if mode == "prefix":
        length = params.get("length")
        if not isinstance(length, int) or length <= 0:
            raise GroupingSpecError("prefix mode requires positive integer length")
        lower = bool(params.get("lower", False))
        try:
            expr = helper.string_prefix_expr(column_expr, length, lower)
        except NotImplementedError as exc:
            raise GroupingSpecError("prefix grouping is not supported by this dialect") from exc
        max_groups = params.get("max_groups")
        if max_groups is None and bins:
            max_groups = max(bins * 4, bins)
        counts = helper.value_counts_expr(expr, max_groups=max_groups)
        segments = []
        collected = []
        total_seen = 0
        for value, count in counts:
            total_seen += count
            if value is None:
                segments.append(PartitionSegment(label="__null__", is_null=True, count=count))
            else:
                collected.append(value)
                segments.append(
                    PartitionSegment(
                        label=str(value),
                        include_values=[value],
                        count=count,
                        value_expr=expr,
                    )
                )
        if params.get("other", True):
            if total_rows is not None and total_rows > total_seen:
                other_count = total_rows - total_seen
            else:
                if collected:
                    predicate = (
                        f"{expr} NOT IN ({helper.render_in_list(collected)}) "
                        f"AND {expr} IS NOT NULL"
                    )
                else:
                    predicate = f"{expr} IS NOT NULL"
                other_count = helper.count_predicate(predicate)
            if other_count:
                segments.append(
                    PartitionSegment(
                        label="__other__",
                        exclude_values=collected,
                        count=other_count,
                        value_expr=expr,
                    )
                )
        return pack_segments(segments, bins=bins)

    if mode == "explicit_values":
        values = params.get("values")
        if not isinstance(values, (list, tuple)):
            raise GroupingSpecError("explicit_values mode requires values list")
        unique_values = []
        includes_null = False
        for value in values:
            if value is None:
                includes_null = True
                continue
            if value not in unique_values:
                unique_values.append(value)
        segments = []
        for value in unique_values:
            predicate = f"{column_expr} = {helper.render_literal(value)}"
            count = helper.count_predicate(predicate)
            segments.append(
                PartitionSegment(label=str(value), include_values=[value], count=count)
            )
        if includes_null:
            null_count = helper.null_count_expr(column_expr)
            if null_count:
                segments.append(
                    PartitionSegment(label="__null__", is_null=True, count=null_count)
                )
        if params.get("other", True):
            if unique_values:
                predicate = (
                    f"{column_expr} NOT IN ({helper.render_in_list(unique_values)}) "
                    f"AND {column_expr} IS NOT NULL"
                )
            else:
                predicate = f"{column_expr} IS NOT NULL"
            count = helper.count_predicate(predicate)
            if count:
                segments.append(
                    PartitionSegment(
                        label="__other__",
                        exclude_values=unique_values,
                        count=count,
                    )
                )
        return segments

    if mode == "hash":
        buckets = params.get("buckets") or params.get("mod") or bins
        if not isinstance(buckets, int) or buckets <= 0:
            raise GroupingSpecError("hash mode requires positive integer buckets")
        if total_rows is not None and 0 < total_rows < buckets:
            buckets = total_rows
        target_bins = min(bins or buckets, buckets)
        bucket_ids = list(range(buckets))
        group_size = max(1, math.ceil(buckets / target_bins))
        groups = [bucket_ids[idx : idx + group_size] for idx in range(0, buckets, group_size)]
        segments = []
        for idx, group in enumerate(groups):
            try:
                predicate = helper.hash_filter(column_name, buckets, group)
            except NotImplementedError as exc:
                raise GroupingSpecError("hash grouping is not supported by this dialect") from exc
            count = helper.count_predicate(predicate)
            segments.append(
                PartitionSegment(
                    label=f"hash_{idx}",
                    hash_mod=buckets,
                    buckets=group,
                    count=count,
                )
            )
        null_count = helper.null_count_expr(column_expr)
        if null_count:
            segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
        return segments

    raise GroupingSpecError(f"unsupported string grouping mode: {mode}")


def _build_numeric_segments(
    helper,
    column_expr: str,
    column_name: str,
    mode: str,
    params: dict,
    total_rows: Optional[int],
    bins: int,
) -> list[PartitionSegment]:
    if mode == "ranges":
        ranges = params.get("ranges")
        if not isinstance(ranges, (list, tuple)):
            raise GroupingSpecError("ranges mode requires ranges list")
        normalized = _normalize_ranges(ranges)
        segments = []
        for start, end, include_end in normalized:
            count = helper.count_range_expr(column_expr, start, end, include_end)
            segments.append(
                PartitionSegment(
                    label=f"[{start},{end}{']' if include_end else ')'}",
                    range_start=start,
                    range_end=end,
                    include_end=include_end,
                    count=count,
                )
            )
        null_count = helper.null_count_expr(column_expr)
        if null_count:
            segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
        return segments

    if mode == "step":
        start = params.get("start")
        step = params.get("step")
        bins_override = params.get("bins")
        min_value, max_value = helper.min_max_expr(column_expr)
        if min_value is None or max_value is None:
            null_count = helper.null_count_expr(column_expr)
            segments = [PartitionSegment(label="__all__", count=total_rows)]
            if null_count:
                segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
            return segments
        if start is None:
            start = min_value
        use_decimal = any(isinstance(value, Decimal) for value in (start, max_value, step))
        if use_decimal:
            if not isinstance(start, Decimal):
                start = Decimal(str(start))
            if not isinstance(max_value, Decimal):
                max_value = Decimal(str(max_value))
            if step is not None and not isinstance(step, Decimal):
                step = Decimal(str(step))

        if step is not None:
            if not isinstance(step, (int, float, Decimal)) or step <= 0:
                raise GroupingSpecError("step must be positive number")
            if bins_override is None:
                diff = max_value - start
                if use_decimal:
                    bins_override = max(1, math.ceil(diff / step))
                else:
                    bins_override = max(1, math.ceil(diff / float(step)))
        if bins_override is None:
            bins_override = bins
        if bins_override is not None and total_rows and bins_override > total_rows:
            bins_override = total_rows
        if step is None:
            diff = max_value - start
            if use_decimal:
                step = diff / Decimal(bins_override or 1)
            else:
                step = diff / float(bins_override or 1)
        if step <= 0:
            step = Decimal("1") if use_decimal else 1
        segments = []
        cursor = start
        for idx in range(int(bins_override)):
            end = max_value if idx == bins_override - 1 else cursor + step
            include_end = idx == bins_override - 1
            count = helper.count_range_expr(column_expr, cursor, end, include_end)
            segments.append(
                PartitionSegment(
                    label=f"[{cursor},{end}{']' if include_end else ')'}",
                    range_start=cursor,
                    range_end=end,
                    include_end=include_end,
                    count=count,
                )
            )
            cursor = end
        null_count = helper.null_count_expr(column_expr)
        if null_count:
            segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
        return segments

    if mode in ("quantiles", "percentiles"):
        if mode == "quantiles":
            buckets = params.get("k")
            if not isinstance(buckets, int) or buckets <= 1:
                raise GroupingSpecError("quantiles mode requires integer k > 1")
            percentiles = [idx / float(buckets) for idx in range(1, buckets)]
        else:
            percentiles = params.get("percentiles")
            if not isinstance(percentiles, (list, tuple)):
                raise GroupingSpecError("percentiles mode requires percentiles list")
            percentiles = _normalize_percentiles(percentiles)
        try:
            bounds = helper.quantile_values(column_expr, percentiles)
        except NotImplementedError as exc:
            raise GroupingSpecError("quantiles are not supported by this dialect") from exc
        min_value, max_value = helper.min_max_expr(column_expr)
        if min_value is None or max_value is None:
            null_count = helper.null_count_expr(column_expr)
            segments = [PartitionSegment(label="__all__", count=total_rows)]
            if null_count:
                segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
            return segments
        normalized_bounds = [bound for bound in bounds if bound is not None]
        normalized_bounds = sorted(set(normalized_bounds))
        segments = []
        cursor = min_value
        for bound in normalized_bounds:
            if bound <= cursor:
                continue
            count = helper.count_range_expr(column_expr, cursor, bound, False)
            segments.append(
                PartitionSegment(
                    label=f"[{cursor},{bound})",
                    range_start=cursor,
                    range_end=bound,
                    include_end=False,
                    count=count,
                )
            )
            cursor = bound
        count = helper.count_range_expr(column_expr, cursor, max_value, True)
        segments.append(
            PartitionSegment(
                label=f"[{cursor},{max_value}]",
                range_start=cursor,
                range_end=max_value,
                include_end=True,
                count=count,
            )
        )
        null_count = helper.null_count_expr(column_expr)
        if null_count:
            segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
        return segments

    if mode == "hash":
        buckets = params.get("buckets") or params.get("mod") or bins
        if not isinstance(buckets, int) or buckets <= 0:
            raise GroupingSpecError("hash mode requires positive integer buckets")
        if total_rows is not None and 0 < total_rows < buckets:
            buckets = total_rows
        target_bins = min(bins or buckets, buckets)
        bucket_ids = list(range(buckets))
        group_size = max(1, math.ceil(buckets / target_bins))
        groups = [bucket_ids[idx : idx + group_size] for idx in range(0, buckets, group_size)]
        segments = []
        for idx, group in enumerate(groups):
            try:
                predicate = helper.hash_filter(column_name, buckets, group)
            except NotImplementedError as exc:
                raise GroupingSpecError("hash grouping is not supported by this dialect") from exc
            count = helper.count_predicate(predicate)
            segments.append(
                PartitionSegment(
                    label=f"hash_{idx}",
                    hash_mod=buckets,
                    buckets=group,
                    count=count,
                )
            )
        null_count = helper.null_count_expr(column_expr)
        if null_count:
            segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
        return segments

    raise GroupingSpecError(f"unsupported numeric grouping mode: {mode}")


def _build_date_segments(
    helper,
    column_expr: str,
    mode: str,
    params: dict,
    total_rows: Optional[int],
    bins: int,
    partition_granularity: Optional[str],
) -> list[PartitionSegment]:
    if mode == "ranges":
        ranges = params.get("ranges")
        if not isinstance(ranges, (list, tuple)):
            raise GroupingSpecError("ranges mode requires ranges list")
        normalized = _normalize_ranges(ranges)
        segments = []
        for start, end, include_end in normalized:
            count = helper.count_range_expr(column_expr, start, end, include_end)
            segments.append(
                PartitionSegment(
                    label=f"[{start},{end}{']' if include_end else ')'}",
                    range_start=start,
                    range_end=end,
                    include_end=include_end,
                    count=count,
                )
            )
        null_count = helper.null_count_expr(column_expr)
        if null_count:
            segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
        return segments

    if mode == "step":
        start = params.get("start")
        step = params.get("step")
        bins_override = params.get("bins")
        min_value, max_value = helper.min_max_expr(column_expr)
        if min_value is None or max_value is None:
            null_count = helper.null_count_expr(column_expr)
            segments = [PartitionSegment(label="__all__", count=total_rows)]
            if null_count:
                segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
            return segments
        if start is None:
            start = min_value
        step_delta = None
        if step is not None:
            if not isinstance(step, (int, float)) or step <= 0:
                raise GroupingSpecError("step must be positive number")
            if isinstance(start, datetime):
                step_delta = timedelta(seconds=float(step))
            elif isinstance(start, date):
                step_delta = timedelta(days=float(step))
            else:
                raise GroupingSpecError("step mode requires datetime/date start value")
            if bins_override is None:
                delta = max_value - start
                total_seconds = (
                    delta.total_seconds() if hasattr(delta, "total_seconds") else float(delta)
                )
                step_seconds = step_delta.total_seconds()
                bins_override = max(1, math.ceil(total_seconds / step_seconds))
        if bins_override is None:
            bins_override = bins
        if bins_override is not None and total_rows and bins_override > total_rows:
            bins_override = total_rows

        if step_delta is None:
            delta = max_value - start
            total_seconds = (
                delta.total_seconds() if hasattr(delta, "total_seconds") else float(delta)
            )
            step_seconds = total_seconds / float(bins_override or 1)
            step_delta = timedelta(seconds=step_seconds)
        segments = []
        cursor = start
        for idx in range(int(bins_override)):
            end = max_value if idx == bins_override - 1 else cursor + step_delta
            include_end = idx == bins_override - 1
            count = helper.count_range_expr(column_expr, cursor, end, include_end)
            segments.append(
                PartitionSegment(
                    label=f"[{cursor},{end}{']' if include_end else ')'}",
                    range_start=cursor,
                    range_end=end,
                    include_end=include_end,
                    count=count,
                )
            )
            cursor = end
        null_count = helper.null_count_expr(column_expr)
        if null_count:
            segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
        return segments

    if mode == "granularity":
        granularity = params.get("granularity") or partition_granularity or "day"
        allowed = {"hour", "day", "week", "month", "year"}
        if granularity not in allowed:
            raise GroupingSpecError(f"unsupported granularity: {granularity}")
        min_value, max_value = helper.min_max_expr(column_expr)
        if min_value is None or max_value is None:
            null_count = helper.null_count_expr(column_expr)
            segments = [PartitionSegment(label="__all__", count=total_rows)]
            if null_count:
                segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
            return segments
        cursor = floor_to_granularity(min_value, granularity)
        segments = []
        while cursor < max_value:
            end = advance_granularity(cursor, granularity)
            count = helper.count_range_expr(column_expr, cursor, end, False)
            segments.append(
                PartitionSegment(
                    label=f"[{cursor},{end})",
                    range_start=cursor,
                    range_end=end,
                    include_end=False,
                    count=count,
                )
            )
            cursor = end
        count = helper.count_range_expr(column_expr, cursor, max_value, True)
        segments.append(
            PartitionSegment(
                label=f"[{cursor},{max_value}]",
                range_start=cursor,
                range_end=max_value,
                include_end=True,
                count=count,
            )
        )
        null_count = helper.null_count_expr(column_expr)
        if null_count:
            segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
        return segments

    raise GroupingSpecError(f"unsupported datetime grouping mode: {mode}")


def _build_bool_segments(
    helper,
    column_expr: str,
    mode: str,
    params: dict,
    total_rows: Optional[int],
) -> list[PartitionSegment]:
    if mode in ("as_is", "as-is"):
        counts = helper.value_counts_expr(column_expr, max_groups=None)
        segments = []
        for value, count in counts:
            if value is None:
                segments.append(PartitionSegment(label="__null__", is_null=True, count=count))
            else:
                segments.append(
                    PartitionSegment(
                        label=str(bool(value)),
                        include_values=[bool(value)],
                        count=count,
                    )
                )
        return segments

    if mode == "explicit_values":
        values = params.get("values")
        if not isinstance(values, (list, tuple)):
            raise GroupingSpecError("explicit_values mode requires values list")
        normalized = _normalize_bool_values(values)
        segments = []
        includes_null = False
        for value in normalized:
            if value is None:
                includes_null = True
                continue
            predicate = f"{column_expr} = {helper.render_literal(value)}"
            count = helper.count_predicate(predicate)
            segments.append(
                PartitionSegment(label=str(value), include_values=[value], count=count)
            )
        if includes_null:
            null_count = helper.null_count_expr(column_expr)
            if null_count:
                segments.append(PartitionSegment(label="__null__", is_null=True, count=null_count))
        if params.get("other", False) and total_rows is not None:
            filtered = [value for value in normalized if value is not None]
            if filtered:
                predicate = (
                    f"{column_expr} NOT IN ({helper.render_in_list(filtered)}) "
                    f"AND {column_expr} IS NOT NULL"
                )
            else:
                predicate = f"{column_expr} IS NOT NULL"
            count = helper.count_predicate(predicate)
            segments.append(
                PartitionSegment(
                    label="__other__",
                    exclude_values=filtered,
                    count=count,
                )
            )
        return segments

    raise GroupingSpecError(f"unsupported bool grouping mode: {mode}")
