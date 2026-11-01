# src/sim/interfaces.py
from typing import List, Tuple, Optional, Any
from abc import ABC, abstractmethod

class Route:
    """Owner: R2 (Map & Network Graph Lead)"""
    def __init__(self, path: List[Tuple[int, float, Optional[str]]]):
        self.path = path  # [(node, planned_eta, order_id_or_none)]

class Planner(ABC):
    """Owner: R4/R5 (Allocation & Routing Leads)"""
    @abstractmethod
    def plan(self, vehicle: Any, orders: List[Any], world_view: Any, t: float) -> Route:
        pass

class Predictor(ABC):
    """Owner: R6 (Traffic Predictor Lead)"""
    @abstractmethod
    def predict(self, edge: Tuple[int, int], t_now: float, horizon: int) -> float:
        pass

class Trigger(ABC):
    """Owner: R4 (Negotiation Trigger Lead)"""
    @abstractmethod
    def should_negotiate(self, vehicle: Any, routes: List[Route], t: float) -> bool:
        pass

class Negotiator(ABC):
    """Owner: R5 (Auction & Bargaining Lead)"""
    @abstractmethod
    def resolve(self, conflict: Any) -> Any:
        pass

class MetricsLogger(ABC):
    """Owner: R8 (Benchmark & Replay Lead)"""
    @abstractmethod
    def log(self, event_type: str, timestamp: float, data: dict):
        pass