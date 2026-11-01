# src/sim/models.py
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Order:
    id: str
    node: int
    demand: float
    priority: int
    tw_start: float
    tw_end: float
    service_time: float
    release_time: float

@dataclass
class Vehicle:
    id: str
    depot_node: int
    capacity: float
    current_node: int
    allowed_road_classes: Optional[List[str]] = None
    current_edge: Optional[tuple] = None
    load: float = 0.0
    remaining_route: List[int] = field(default_factory=list)

@dataclass
class Event:
    t: float
    type: str  # "traffic_spike", "closure", "new_order"
    target: str
    magnitude: float
    duration: float