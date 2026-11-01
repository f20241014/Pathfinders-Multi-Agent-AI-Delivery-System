# src/sim/world.py
import math
import logging
from typing import Dict, List, Tuple, Callable
from src.sim.models import Event

logger = logging.getLogger(__name__)


class World:
    def __init__(self, graph=None, traffic=None, predictor=None):
        if graph is None:
            from src.world.graph_loader import load_road_graph
            self.G = load_road_graph("secunderabad")
        else:
            self.G = graph

        self.traffic = traffic
        self.predictor = predictor
        self.active_disruptions: Dict[Tuple[int, int], List[Event]] = {}

    @classmethod
    def from_defaults(cls, seed: int = 42):
        from src.world.graph_loader import load_road_graph
        G = load_road_graph("secunderabad")

        traffic = None
        predictor = None

        try:
            from src.world.traffic_model import TrafficModel
            traffic = TrafficModel.from_graph("data/raw/metr-la.h5", seed=seed)
        except Exception as e:
            logger.warning(f"TrafficModel unavailable ({e}). Fallback to 1.0x free-flow times.")

        try:
            from src.prediction.predictor import Predictor
            if traffic is not None:
                predictor = Predictor(traffic)
        except Exception as e:
            logger.warning(f"Predictor unavailable ({e}). Fallback to free-flow estimates.")

        return cls(graph=G, traffic=traffic, predictor=predictor)

    def _get_free_flow_time(self, u: int, v: int) -> float:
        if not self.G.has_edge(u, v):
            raise KeyError(f"Edge ({u}, {v}) does not exist in graph.")
        edges = self.G[u][v]
        return min(data.get("free_flow_time", 10.0) for data in edges.values())

    def add_disruption(self, event: Event):
        if isinstance(event.target, tuple):
            u, v = event.target
        elif isinstance(event.target, str) and "," in event.target:
            u_str, v_str = event.target.split(",")
            u, v = int(u_str), int(v_str)
        else:
            return

        edge_key = (u, v)
        if edge_key not in self.active_disruptions:
            self.active_disruptions[edge_key] = []
        self.active_disruptions[edge_key].append(event)

    def is_blocked(self, u: int, v: int, t: float) -> bool:
        edge_key = (u, v)
        if edge_key in self.active_disruptions:
            for ev in self.active_disruptions[edge_key]:
                if ev.type == "closure" and ev.t <= t < (ev.t + ev.duration):
                    return True
        return False

    def edge_time(self, u: int, v: int, t: float) -> float:
        if self.is_blocked(u, v, t):
            return math.inf

        base_time = self._get_free_flow_time(u, v)

        # Traffic Model Multiplier (R6)
        t_mult = 1.0
        if self.traffic is not None:
            try:
                t_mult = self.traffic.actual_multiplier_uv(str(u), str(v), t)
            except Exception:
                t_mult = 1.0

        # Disruption Spikes
        spike_mult = 1.0
        edge_key = (u, v)
        if edge_key in self.active_disruptions:
            for ev in self.active_disruptions[edge_key]:
                if ev.type == "traffic_spike" and ev.t <= t < (ev.t + ev.duration):
                    spike_mult *= ev.magnitude

        return base_time * t_mult * spike_mult

    def predicted_time(self, u: int, v: int, t: float, horizon_min: int = 15) -> float:
        if self.predictor is not None and self.traffic is not None:
            try:
                edge_idx = self.traffic.edge_index.get((str(u), str(v)))
                if edge_idx is not None:
                    free_flow_s = self._get_free_flow_time(u, v)
                    return self.predictor.predicted_time(edge_idx, t, horizon_min, free_flow_s)
            except Exception:
                pass
        return self._get_free_flow_time(u, v)

    def cost_fn_at(self, t: float) -> Callable[[int, int, dict], float]:
        def cost_fn(u: int, v: int, data: dict) -> float:
            return self.edge_time(u, v, t)
        return cost_fn

    def graph(self):
        return self.G


class FakeWorld:
    """Mock World object for testing without external data dependencies."""

    def __init__(self, graph, speed_mps: float = 10.0, multiplier: float = 1.0):
        self.G = graph
        self.speed_mps = speed_mps
        self.multiplier = multiplier
        self.active_disruptions: Dict[Tuple[int, int], List[Event]] = {}

    def add_disruption(self, event: Event):
        if isinstance(event.target, tuple):
            edge_key = event.target
        elif isinstance(event.target, str) and "," in event.target:
            u_str, v_str = event.target.split(",")
            edge_key = (int(u_str), int(v_str))
        else:
            return

        if edge_key not in self.active_disruptions:
            self.active_disruptions[edge_key] = []
        self.active_disruptions[edge_key].append(event)

    def is_blocked(self, u: int, v: int, t: float) -> bool:
        edge_key = (u, v)
        if edge_key in self.active_disruptions:
            for ev in self.active_disruptions[edge_key]:
                if ev.type == "closure" and ev.t <= t < (ev.t + ev.duration):
                    return True
        return False

    def edge_time(self, u: int, v: int, t: float) -> float:
        if self.is_blocked(u, v, t):
            return math.inf

        length = 100.0
        if self.G.has_edge(u, v):
            edges = self.G[u][v]
            length = min(data.get("length", 100.0) for data in edges.values())

        base_time = (length / self.speed_mps) * self.multiplier

        spike_mult = 1.0
        edge_key = (u, v)
        if edge_key in self.active_disruptions:
            for ev in self.active_disruptions[edge_key]:
                if ev.type == "traffic_spike" and ev.t <= t < (ev.t + ev.duration):
                    spike_mult *= ev.magnitude

        return base_time * spike_mult

    def predicted_time(self, u: int, v: int, t: float, horizon_min: int = 15) -> float:
        return self.edge_time(u, v, t)

    def cost_fn_at(self, t: float) -> Callable[[int, int, dict], float]:
        def cost_fn(u: int, v: int, data: dict) -> float:
            return self.edge_time(u, v, t)
        return cost_fn

    def graph(self):
        return self.G
