from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Order:
    id: str
    node: int
    demand: float
    priority: int = 1
    tw_start: float = 0.0
    tw_end: float = 86400.0
    service_time: float = 300.0
    release_time: float = 0.0


@dataclass
class Vehicle:
    id: str
    depot_node: int
    capacity: float
    current_node: int
    remaining_route: List[int] = field(default_factory=list)
    load: float = 0.0
    allowed_road_classes: Optional[List[str]] = None
    current_edge: Optional[Tuple[int, int, int]] = None

    @property
    def current_load(self) -> float:
        """Alias of load (R3's rules read current_load)."""
        return self.load


@dataclass
class Event:
    t: float
    event_type: str
    payload: dict = field(default_factory=dict)
