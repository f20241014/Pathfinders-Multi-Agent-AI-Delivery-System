"""Road world for the simulator: travel times, closures and traffic spikes.

All times are absolute seconds from midnight (t = start_time_s + env.now).
"""
import logging
import math
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import networkx as nx

logger = logging.getLogger(__name__)

EdgeId = Tuple[int, int, int]
DEFAULT_MAP_PATH = "data/processed/secunderabad.graphml"
DEFAULT_LENGTH_M = 100.0


class World:
    def __init__(
        self,
        graph: nx.MultiDiGraph,
        traffic_model=None,
        predictor=None,
        speed_mps: float = 10.0,
    ):
        self.G = graph
        self.traffic_model = traffic_model
        self.predictor = predictor
        self.speed_mps = speed_mps
        # edge -> list of (start_t, expiry_t)
        self.closures: Dict[EdgeId, List[Tuple[float, float]]] = {}
        # edge -> list of (start_t, expiry_t, multiplier)
        self.spikes: Dict[EdgeId, List[Tuple[float, float, float]]] = {}
        self._warned_default_length = False

    def graph(self) -> nx.MultiDiGraph:
        return self.G

    def _check_edge(self, u, v, key) -> None:
        if not self.G.has_edge(u, v, key):
            raise KeyError(f"Edge ({u}, {v}, {key}) not found in road graph.")

    # ------------------------------------------------------------------
    # Static travel time
    # ------------------------------------------------------------------
    def free_flow_time(self, u, v, key: int = 0) -> float:
        """Seconds to drive the edge with no traffic."""
        self._check_edge(u, v, key)
        data = self.G[u][v][key]
        if "free_flow_time" in data:          # set by R2's load_road_graph
            return float(data["free_flow_time"])
        if "length" in data:
            return float(data["length"]) / self.speed_mps
        if "weight" in data:
            return float(data["weight"]) / self.speed_mps
        if not self._warned_default_length:
            logger.warning(
                "Edge (%s, %s, %s) has no free_flow_time/length/weight; "
                "assuming %.0f m (warning shown once).",
                u, v, key, DEFAULT_LENGTH_M,
            )
            self._warned_default_length = True
        return DEFAULT_LENGTH_M / self.speed_mps

    def edge_key(self, u, v) -> int:
        """Key of the fastest road u -> v (not always 0 on the real graph)."""
        if not self.G.has_edge(u, v):
            raise KeyError(f"Edge ({u}, {v}) not found in road graph.")
        return min(self.G[u][v], key=lambda k: self.free_flow_time(u, v, k))

    # ------------------------------------------------------------------
    # Disruptions
    # ------------------------------------------------------------------
    def add_disruption(
        self, u, v, key, expiry_t_seconds: float,
        start_t_seconds: float = -math.inf,
    ) -> None:
        """Close the road for start_t_seconds <= t < expiry_t_seconds."""
        self._check_edge(u, v, key)
        self.closures.setdefault((u, v, key), []).append(
            (start_t_seconds, expiry_t_seconds)
        )

    def add_spike(
        self, u, v, key, multiplier: float, expiry_t_seconds: float,
        start_t_seconds: float = -math.inf,
    ) -> None:
        """Multiply the road's travel time while start <= t < expiry."""
        self._check_edge(u, v, key)
        self.spikes.setdefault((u, v, key), []).append(
            (start_t_seconds, expiry_t_seconds, multiplier)
        )

    def is_blocked(self, u, v, t: float, key: Optional[int] = None) -> bool:
        """True while the road is closed at time t (key None = fastest road u -> v)."""
        if key is None:
            key = self.edge_key(u, v)
        self._check_edge(u, v, key)
        return any(
            start <= t < expiry
            for start, expiry in self.closures.get((u, v, key), [])
        )

    def active_closures(self, t: float) -> Set[EdgeId]:
        """Roads (u, v, key) closed at time t."""
        return {
            edge for edge, windows in self.closures.items()
            if any(start <= t < expiry for start, expiry in windows)
        }

    def reachable_from(self, source, closed: Iterable[EdgeId] = ()) -> Set:
        """Nodes reachable from source (itself included) with the given roads removed.

        A parallel road u -> v with another key keeps u -> v connected.
        """
        if source not in self.G:
            return set()
        view = nx.restricted_view(self.G, [], list(closed))
        return nx.descendants(view, source) | {source}

    def has_path(self, source, target, closed: Iterable[EdgeId] = ()) -> bool:
        """True if target is reachable from source with the given roads removed."""
        if source not in self.G or target not in self.G:
            return False
        view = nx.restricted_view(self.G, [], list(closed))
        return nx.has_path(view, source, target)

    def spike_multiplier(self, u, v, t: float, key: Optional[int] = None) -> float:
        """Product of the spikes active at time t (1.0 if none)."""
        if key is None:
            key = self.edge_key(u, v)
        self._check_edge(u, v, key)
        mult = 1.0
        for start, expiry, m in self.spikes.get((u, v, key), []):
            if start <= t < expiry:
                mult *= m
        return mult

    # ------------------------------------------------------------------
    # Dynamic travel time
    # ------------------------------------------------------------------
    def traffic_multiplier(self, u, v, t_seconds: float) -> float:
        """R6 ground-truth congestion multiplier, or 1.0 without a model."""
        if self.traffic_model is None:
            return 1.0
        # TODO(R6): confirm TrafficModel expects absolute seconds from
        # midnight (our clock) and that step 0 of its table is 00:00.
        try:
            return float(
                self.traffic_model.actual_multiplier_uv(str(u), str(v), t_seconds)
            )
        except KeyError:
            return 1.0

    def edge_time(self, u, v, t: float, key: Optional[int] = None) -> float:
        """Actual travel time at time t: free-flow x traffic x spikes, or inf if closed.

        key None = the fastest road u -> v (self.edge_key), as in the frozen interface.
        """
        if key is None:
            key = self.edge_key(u, v)
        if self.is_blocked(u, v, t, key):
            return math.inf
        return (
            self.free_flow_time(u, v, key)
            * self.traffic_multiplier(u, v, t)
            * self.spike_multiplier(u, v, t, key)
        )

    def predicted_time(self, u, v, t_seconds: float, horizon_min: int = 15) -> float:
        """R6 forecast of the travel time; free-flow if no predictor."""
        free_flow = self.free_flow_time(u, v, self.edge_key(u, v))
        if self.predictor is None or self.traffic_model is None:
            return free_flow
        edge_idx = self.traffic_model.edge_index.get((str(u), str(v)))
        if edge_idx is None:
            return free_flow
        return float(
            self.predictor.predicted_time(edge_idx, t_seconds, horizon_min, free_flow)
        )

    def cost_fn_at(self, t_seconds: float) -> Callable:
        """Edge cost for R2's astar/dijkstra(cost_fn=...) frozen at time t."""
        def cost(u, v, data=None) -> float:
            return self.edge_time(u, v, t_seconds)   # key None = fastest road
        return cost

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def from_defaults(cls, map_path: str = DEFAULT_MAP_PATH, seed: int = 42) -> "World":
        """Real Secunderabad graph plus R6 traffic model when available."""
        from src.world.graph_loader import load_road_graph

        G = load_road_graph(Path(map_path).stem)

        traffic_model: Optional[object] = None
        predictor: Optional[object] = None
        try:
            from src.world.traffic_model import TrafficModel
            traffic_model = TrafficModel.from_graph(map_path, seed=seed)
        except (ImportError, FileNotFoundError) as e:
            logger.warning("Traffic model unavailable, using free-flow times: %s", e)
        if traffic_model is not None:
            try:
                from src.prediction.predictor import Predictor
                predictor = Predictor(traffic_model)
            except (ImportError, FileNotFoundError) as e:
                logger.warning("Predictor unavailable, predictions use free-flow: %s", e)
        return cls(G, traffic_model=traffic_model, predictor=predictor)


class FakeWorld(World):
    """World with no traffic model, for tests. Same behaviour and errors."""

    def __init__(self, graph: nx.MultiDiGraph, speed_mps: float = 10.0):
        super().__init__(graph, traffic_model=None, predictor=None, speed_mps=speed_mps)
