from abc import ABC, abstractmethod
from typing import List, Dict, Any


class Route:
    def __init__(self, nodes: List[int], expected_times: List[float]):
        self.nodes = nodes
        self.expected_times = expected_times


class Planner(ABC):
    @abstractmethod
    def plan(
        self, vehicles: List[Any], orders: List[Any]
    ) -> Dict[str, Route]:
        pass


class PredictorInterface(ABC):
    @abstractmethod
    def predict(
        self, edge_idx: int, t_now_s: float, horizon_min: int = 15
    ) -> float:
        """Predict travel time multiplier for edge at t_now_s."""
        pass


# Alias to maintain backwards compatibility
Predictor = PredictorInterface


class Trigger(ABC):
    @abstractmethod
    def should_replan(self, state: Dict[str, Any]) -> bool:
        pass


class Negotiator(ABC):
    @abstractmethod
    def negotiate(
        self, requests: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        pass


class MetricsLogger(ABC):
    @abstractmethod
    def log(
        self, event_type: str, timestamp: float, payload: Dict[str, Any]
    ) -> None:
        pass
