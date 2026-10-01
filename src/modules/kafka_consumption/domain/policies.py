from .entities import PartitionCommitResult
from .exceptions import KafkaInputError, KafkaPositionError
from .value_objects import nonnegative


def validate_position(position: int, beginning: int, end: int) -> int:
    for name, value in (("position", position), ("beginning", beginning), ("end", end)):
        nonnegative(value, name)
    if not beginning <= position <= end:
        raise KafkaPositionError(
            f"Position {position} is outside available range [{beginning}, {end}]"
        )
    return position


def select_start_position(
    *,
    mode: str,
    beginning: int,
    end: int,
    committed: int | None = None,
    missing_policy: str = "earliest",
    timestamp_position: int | None = None,
    explicit_position: int | None = None,
) -> int:
    if mode == "committed":
        if committed is not None:
            return validate_position(committed, beginning, end)
        if missing_policy == "error":
            raise KafkaPositionError("No committed position")
        if missing_policy not in {"earliest", "latest"}:
            raise KafkaInputError("Unknown missing offset policy")
        mode = missing_policy
    if mode == "earliest":
        return validate_position(beginning, beginning, end)
    if mode == "latest":
        return validate_position(end, beginning, end)
    if mode == "timestamp":
        return validate_position(
            end if timestamp_position is None else min(timestamp_position, end), beginning, end
        )
    if mode == "explicit" and explicit_position is not None:
        return validate_position(explicit_position, beginning, end)
    raise KafkaInputError("Invalid start mode or missing explicit position")


def monotonic_commit(
    partition: int, requested: int, current: int | None, end: int
) -> PartitionCommitResult:
    nonnegative(partition, "partition")
    validate_position(requested, 0, end)
    if current is not None:
        nonnegative(current, "current")
        if current >= requested:
            return PartitionCommitResult(
                partition,
                requested,
                current,
                current,
                "unchanged" if current == requested else "already_ahead",
            )
    return PartitionCommitResult(partition, requested, current, requested, "committed")
