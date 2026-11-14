"""
R3 · KR&R ontology: the entities the rules reason about.

Units (docs/kr_ontology_rules.md, "Units"; proposed to R1 for docs/DECISIONS.md):
    demand, capacity, load      abstract capacity units (D2); 1 unit = median Amazon package volume
    tw_start, tw_end,
    release_time, shift_end     seconds since midnight; the simulated period is 06:00-10:00
                                (21600-36000 s, D4)
    service_time                seconds
    no time window              tw_start = 0.0, tw_end = 86400.0 (R1's Order defaults);
                                tw_of() returns None for exactly that pair (and for None)

Order is R1's src.sim.models.Order (no copy). Vehicle is R1's Vehicle plus the two attributes only
the rules need: vehicle_class (KR-3, KR-6) and shift_end (KR-10). Rules read every object
through the accessors at the bottom, so plain R1 Vehicles work too (a missing attribute means
the most permissive value).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.sim.models import Order  # noqa: F401  (re-exported: R3 code imports Order from here)
from src.sim.models import Vehicle as SimVehicle

# Road classes as OSM `highway` tags. Large vehicles avoid narrow roads (KR-3).
NARROW_ROAD_CLASSES = frozenset({"residential", "living_street", "service", "unclassified"})
ALL_ROAD_CLASSES = frozenset(
    {"motorway", "trunk", "primary", "secondary", "tertiary"} | NARROW_ROAD_CLASSES
)

PRIORITY_EXPRESS, PRIORITY_STANDARD, PRIORITY_ECONOMY = 1, 2, 3
SIM_START_S = 6 * 3600.0  # 06:00 (D4)
SIM_END_S = 10 * 3600.0  # 10:00 (D4)
# "No time window" = R1's Order defaults, so R1's simulator can load every order (never None).
NO_TW_START = 0.0
NO_TW_END = 86400.0


@dataclass
class Vehicle(SimVehicle):
    """R1's Vehicle with the rule-only attributes. current_node defaults to the depot."""

    current_node: Optional[int] = None
    vehicle_class: str = "small"  # "small" | "large"
    shift_end: Optional[float] = None  # seconds since midnight; None = no limit

    def __post_init__(self):
        if self.current_node is None:
            self.current_node = self.depot_node


@dataclass(frozen=True)
class Zone:
    """Nodes with a time-dependent restriction, e.g. no large vehicles 08:00-10:00 (KR-6).

    TODO(R2): which areas of the map are zones, and their hours.
    """

    id: str
    nodes: frozenset
    banned_classes: frozenset = frozenset({"large"})
    start: float = 0.0  # restricted interval [start, end), seconds since midnight
    end: float = 0.0

    def restricts(self, vehicle_class: str, t: float) -> bool:
        return vehicle_class in self.banned_classes and self.start <= t < self.end


# ------------------------------------------------------------------ accessors
def tw_of(order):
    """(tw_start, tw_end), or None when the order has no time window.

    No window = R1's defaults (0.0, 86400.0), exactly that pair. None is also read as "no window"
    so older objects still work, but the generator never writes None.
    """
    s, e = getattr(order, "tw_start", None), getattr(order, "tw_end", None)
    if s is None or e is None:
        return None
    s, e = float(s), float(e)
    return None if (s, e) == (NO_TW_START, NO_TW_END) else (s, e)


def shift_end_of(vehicle) -> float:
    end = getattr(vehicle, "shift_end", None)
    return float("inf") if end is None else float(end)


def class_of(vehicle) -> str:
    return getattr(vehicle, "vehicle_class", None) or "small"


def allowed_classes_of(vehicle):
    """Set of allowed road classes; R1 uses None to mean 'all roads'."""
    allowed = getattr(vehicle, "allowed_road_classes", None)
    return ALL_ROAD_CLASSES if allowed is None else frozenset(allowed)


def position_of(vehicle):
    node = getattr(vehicle, "current_node", None)
    return vehicle.depot_node if node is None else node
