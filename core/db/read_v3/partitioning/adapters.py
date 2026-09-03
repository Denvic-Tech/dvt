from dataclasses import dataclass
from typing import Optional

from core.db.read_v3.errors import ReadV3ConfigError
from core.db.read_v3.models import PartitionStrategy, ValueKind


ORDERABLE_KINDS = {
    ValueKind.NUMERIC,
    ValueKind.DATE,
    ValueKind.DATETIME,
    ValueKind.STRING,
    ValueKind.UUID,
}


@dataclass(frozen=True)
class PartitionAdapter:
    strategy: PartitionStrategy
    reason: str


def normalize_strategy(raw: Optional[str]) -> Optional[PartitionStrategy]:
    if raw is None:
        return None
    norm = raw.strip().lower()
    if norm not in {PartitionStrategy.RANGE.value, PartitionStrategy.HASH.value}:
        raise ReadV3ConfigError(
            f"Unsupported partition_grouping mode={raw!r}. Allowed values: range, hash"
        )
    return PartitionStrategy(norm)


def choose_partition_strategy(
    *,
    value_kind: ValueKind,
    has_nulls: bool,
    explicit_strategy: Optional[str],
) -> PartitionAdapter:
    chosen = normalize_strategy(explicit_strategy)

    if chosen is not None:
        if chosen == PartitionStrategy.RANGE and value_kind not in ORDERABLE_KINDS:
            raise ReadV3ConfigError(
                "Range strategy requires an orderable partition key type. "
                f"value_kind={value_kind.value}"
            )
        if chosen == PartitionStrategy.RANGE and has_nulls:
            raise ReadV3ConfigError(
                "Range strategy requires a non-null partition key. "
                "Use partition_grouping mode='hash' for nullable keys."
            )
        return PartitionAdapter(strategy=chosen, reason="explicit strategy")

    if value_kind in ORDERABLE_KINDS and not has_nulls:
        return PartitionAdapter(
            strategy=PartitionStrategy.RANGE,
            reason="orderable non-null key",
        )

    return PartitionAdapter(
        strategy=PartitionStrategy.HASH,
        reason="nullable or non-orderable key",
    )
