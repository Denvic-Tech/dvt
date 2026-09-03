from typing import Any, Sequence

from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.models import ReadSegment


def _ensure_comparable(left: Any, right: Any) -> None:
    try:
        _ = left <= right
    except Exception as exc:  # pragma: no cover - defensive
        raise ReadV3PlanningError(
            f"Division values are not comparable: left={left!r} right={right!r}"
        ) from exc


def validate_divisions(divisions: Sequence[Any], expected_segments: int) -> tuple[Any, ...]:
    if expected_segments <= 0:
        raise ReadV3PlanningError("Expected segment count must be positive")
    if len(divisions) != expected_segments + 1:
        raise ReadV3PlanningError(
            f"Invalid divisions length={len(divisions)} for segments={expected_segments}"
        )
    if any(value is None for value in divisions):
        raise ReadV3PlanningError("Divisions must not contain None in strict read_v3 mode")

    for idx in range(1, len(divisions)):
        prev_v = divisions[idx - 1]
        curr_v = divisions[idx]
        _ensure_comparable(prev_v, curr_v)
        if curr_v < prev_v:
            raise ReadV3PlanningError(
                f"Divisions are not monotonic at index {idx - 1}: {prev_v!r} > {curr_v!r}"
            )

    return tuple(divisions)


def build_divisions_from_segments(segments: Sequence[ReadSegment]) -> tuple[Any, ...]:
    if not segments:
        raise ReadV3PlanningError("Cannot build divisions for an empty segment list")

    divisions = [segments[0].division.start]
    prev_end = segments[0].division.start

    for idx, segment in enumerate(segments):
        start = segment.division.start
        end = segment.division.end
        if idx > 0:
            _ensure_comparable(prev_end, start)
            if start != prev_end:
                raise ReadV3PlanningError(
                    "Segments are not contiguous for known divisions: "
                    f"prev_end={prev_end!r} start={start!r} segment={segment.label!r}"
                )
        divisions.append(end)
        prev_end = end

    return validate_divisions(divisions, expected_segments=len(segments))
