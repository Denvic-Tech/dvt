from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PhysicalDataFrameIndex:
    name: str
    strategy: str
    source_column: str
    bound_column: str | None = None
