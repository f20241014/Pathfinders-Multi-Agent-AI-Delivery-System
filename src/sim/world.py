import logging
from typing import Dict, Tuple
import networkx as nx

logger = logging.getLogger(__name__)


class World:
    def __init__(
        self,
        graph: nx.MultiDiGraph,
        traffic_model=None,
        speed_mps: float = 10.0,
    ):
        self.graph = graph
        self.traffic_model = traffic_model
        self.speed_mps = speed_mps
        self.disruptions: Dict[Tuple[int, int, int], float] = {}

    def free_flow_time(self, u: int, v: int, key: int = 0) -> float:
        if not self.graph.has_edge(u, v, key):
            raise KeyError(f"Edge ({u}, {v}, {key}) not found in road graph.")
        data = self.graph[u][v][key]
        weight = data.get("weight", 100.0)
        return weight / self.speed_mps

    def is_blocked(
        self, u: int, v: int, key: int = 0, t_seconds: float = 0.0
    ) -> bool:
        if not self.graph.has_edge(u, v, key):
            raise KeyError(f"Edge ({u}, {v}, {key}) not found in road graph.")
        expiry = self.disruptions.get((u, v, key), 0.0)
        return t_seconds < expiry

    def edge_time(
        self, u: int, v: int, key: int = 0, t_seconds: float = 0.0
    ) -> float:
        base_time = self.free_flow_time(u, v, key)
        if self.is_blocked(u, v, key, t_seconds):
            return float("inf")
        multiplier = 1.0
        if self.traffic_model is not None:
            multiplier = self.traffic_model.get_multiplier(
                (u, v, key), t_seconds
            )
        return base_time * multiplier

    def add_disruption(
        self, u: int, v: int, key: int, expiry_t_seconds: float
    ):
        self.disruptions[(u, v, key)] = expiry_t_seconds

    @classmethod
    def from_defaults(
        cls, map_path: str = "data/processed/secunderabad.graphml"
    ):
        G = nx.MultiDiGraph()
        G.add_edge(1, 2, key=0, weight=100.0)
        traffic_model = None
        try:
            from src.traffic.model import TrafficModel
            traffic_model = TrafficModel.from_graph(map_path)
        except (ImportError, FileNotFoundError) as e:
            logger.warning("Falling back to free-flow traffic model: %s", e)
        except Exception as e:
            logger.error("Error loading traffic model: %s", e, exc_info=True)
            raise e
        return cls(G, traffic_model=traffic_model)


class FakeWorld(World):
    def __init__(self, graph: nx.MultiDiGraph, speed_mps: float = 10.0):
        super().__init__(graph, traffic_model=None, speed_mps=speed_mps)

    def is_blocked(
        self, u: int, v: int, key: int = 0, t_seconds: float = 0.0
    ) -> bool:
        if not self.graph.has_edge(u, v, key):
            raise KeyError(f"Edge ({u}, {v}, {key}) not found in road graph.")
        return super().is_blocked(u, v, key, t_seconds)

    def edge_time(
        self, u: int, v: int, key: int = 0, t_seconds: float = 0.0
    ) -> float:
        if not self.graph.has_edge(u, v, key):
            raise KeyError(f"Edge ({u}, {v}, {key}) not found in road graph.")
        return super().edge_time(u, v, key, t_seconds)