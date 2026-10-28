from dataclasses import dataclass, field
from typing import List

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
    current_load: float = 0.0
    remaining_route: List[int] = field(default_factory=list)

@dataclass
class Event:
    t: float
    type: str  
    target: str
    magnitude: float
    duration: float