"""Fixed layout geometry and typed calculation results."""

from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite

from ..state import Position

NODE_WIDTH = 360.0
NODE_HEIGHT = 240.0
LAYER_GAP = 140.0
NODE_GAP = 80.0
COMPONENT_GAP = 120.0
GROUP_MIN_WIDTH = 520.0
GROUP_MIN_HEIGHT = 340.0
GROUP_PADDING_X = 80.0
GROUP_PADDING_TOP = 56.0
GROUP_PADDING_BOTTOM = 64.0
COLLAPSED_WIDTH = 360.0
COLLAPSED_HEIGHT = 160.0
ORIGIN = 40.0


class LayoutError(ValueError):
    """The graph cannot be laid out without losing structural integrity."""


@dataclass(frozen=True)
class Size:
    width: float
    height: float


@dataclass(frozen=True, order=True)
class OrderKey:
    y: float
    x: float
    entity_id: str
    kind: str = ""


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def intersects(self, other: "Rect") -> bool:
        return (
            self.x < other.x + other.width
            and other.x < self.x + self.width
            and self.y < other.bottom
            and other.y < self.bottom
        )

    def translated(self, x: float, y: float) -> "Rect":
        return Rect(self.x + x, self.y + y, self.width, self.height)

    def mapping(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass
class Placement[Key]:
    rectangles: dict[Key, Rect]
    bounds: Rect


@dataclass
class LayoutResult:
    node_positions: dict[str, Position]
    subgraph_positions: dict[str, Position]
    bounds: Rect


def bounding_rect(rectangles: Iterable[Rect]) -> Rect:
    rectangles = list(rectangles)
    if not rectangles:
        return Rect(0, 0, 0, 0)
    left = min(rect.x for rect in rectangles)
    top = min(rect.y for rect in rectangles)
    right = max(rect.x + rect.width for rect in rectangles)
    bottom = max(rect.bottom for rect in rectangles)
    return Rect(left, top, right - left, bottom - top)


def assert_disjoint(rectangles: Iterable[Rect]) -> None:
    rectangles = list(rectangles)
    for index, rect in enumerate(rectangles):
        if not all(isfinite(value) for value in (rect.x, rect.y, rect.width, rect.height)):
            raise LayoutError("Calculated geometry must be finite.")
        if any(rect.intersects(other) for other in rectangles[index + 1 :]):
            raise LayoutError("Calculated rectangles overlap.")
