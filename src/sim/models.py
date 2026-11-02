from dataclasses import dataclass, field
from typing import List


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


@dataclass
class Event:
    t: float
    event_type: str
    payload: dict = field(default_factory=dict)
