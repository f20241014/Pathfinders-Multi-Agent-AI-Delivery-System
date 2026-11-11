"""
R3 · KR&R ontology: the entities the rules reason about.

Order follows the frozen interface v1.0 (Section 4.1). Vehicle mirrors R1's dataclass; when R1's
version is merged, import it from there and delete the copy here (field names are the same).
All times are seconds from simulation start.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Road classes as OSM `highway` tags. Large vehicles avoid narrow roads (rule R03).
NARROW_ROAD_CLASSES = frozenset({"residential", "living_street", "service", "unclassified"})
ALL_ROAD_CLASSES = frozenset(
    {"motorway", "trunk", "primary", "secondary", "tertiary"} | NARROW_ROAD_CLASSES
)

PRIORITY_EXPRESS, PRIORITY_STANDARD, PRIORITY_ECONOMY = 1, 2, 3


@dataclass
class Order:
    id: str
    node: int
    demand: int                       # abstract capacity units
    priority: int                     # 1 express, 2 standard, 3 economy
    tw_start: Optional[float] = None  # None = no time window
    tw_end: Optional[float] = None
    service_time: float = 0.0
    release_time: float = 0.0

    @property
    def has_tw(self) -> bool:
        return self.tw_start is not None and self.tw_end is not None


@dataclass
class Vehicle:
    id: str
    depot_node: int
    capacity: int
    vehicle_class: str = "small"      # "small" | "large"
    allowed_road_classes: frozenset = ALL_ROAD_CLASSES
    shift_start: float = 0.0
    shift_end: float = 4 * 3600.0     # D4: 4-hour window
    current_node: Optional[int] = None
    load: int = 0                     # units already on board and not yet delivered
    remaining_route: list = field(default_factory=list)

    def __post_init__(self):
        if self.current_node is None:
            self.current_node = self.depot_node


@dataclass(frozen=True)
class Zone:
    """A set of nodes with a time-dependent restriction, e.g. no large vehicles 08:00-10:00 (rule R06)."""
    id: str
    nodes: frozenset
    banned_classes: frozenset = frozenset({"large"})
    start: float = 0.0                # restricted interval [start, end) in sim seconds
    end: float = 0.0

    def restricts(self, vehicle_class: str, t: float) -> bool:
        return vehicle_class in self.banned_classes and self.start <= t < self.end