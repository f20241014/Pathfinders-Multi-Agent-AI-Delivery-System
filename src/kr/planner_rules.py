"""
R3 · Week 4: the knowledge base inside the planners.

Rules -> blocked edges (KR-3 road class, KR-4 closures, KR-6 zones; KR-5 one-way is the directed
graph). Every planner in the repo treats "cost inf" or "world.is_blocked(...) is True" as a road it
must not use, so the rules only have to answer those two questions per vehicle:

    rules = RoadRules(G, zones)                        # once per map
    rules.cost_fn(vehicle, base_cost_fn, t)            # A*, Dijkstra, Yen, TravelTimeMatrix (R2)
    rules.view(world, vehicle)                         # world as THIS vehicle may use it:
        ReplanningAgent(vehicle, rules.view(world, vehicle), ...)   # R7's D* Lite agents
        WorldTravel(rules.view(world, vehicle), now)                # R4's snapshot paths
        rules.view(world, vehicle).cost_fn_at(t)                    # R1's cost_fn for R2's astar
    rules.blocked_edges(vehicle, t)                    # {(u, v): reason} for logs and explanations

Priority ordering in planners (KR-13 with its KR-8/KR-10 overrides):

    stops, result = priority_stops(vehicle, orders, travel_time, t_now)
    planner.register(vehicle, orders, stops=stops)     # R7's AgentPlanner already takes stops=

Explanation trace in the run log:

    log_kr_trace(env_or_logger, t, vehicle_id, result)  # one "kr_check" row (R1's JSONL format)

Nothing here edits R1/R2/R4/R7 code; the TODOs at the bottom name the one-line hook each owner adds.
Do not give a view to R1's environment itself: the environment moves vehicles on the real world.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Optional

from .ontology import NARROW_ROAD_CLASSES, SIM_START_S, Zone, allowed_classes_of, class_of
from .rules import _road_class, road_allowed, run_feasibility_engine, sort_orders_by_priority

INF = math.inf


def _free_flow_cost(u, v, data):
    """R2's default edge cost (free-flow seconds), without importing src.search at module load."""
    from src.search.dijkstra import free_flow_cost

    return free_flow_cost(u, v, data)


class RoadRules:
    """Road rules for one map. Static class checks are cached per vehicle profile."""

    def __init__(
        self,
        G,
        zones: Iterable[Zone] = (),
        is_blocked: Optional[Callable[[int, int, float], bool]] = None,
    ):
        self.G = G
        self.zones = tuple(zones)
        self.is_blocked = is_blocked
        self._class = {(u, v, k): _road_class(d) for u, v, k, d in G.edges(keys=True, data=True)}
        self._static: dict = {}

    # ------------------------------------------------------------ single edges
    def edge_allowed(self, vehicle, u, v, key, t: float):
        """(ok, reason) for one parallel road u -> v (key), KR-3 and KR-6 only (closures: world)."""
        return road_allowed(vehicle, u, v, {"road_class": self._class[(u, v, key)]}, t, self.zones)

    def class_blocked(self, vehicle) -> dict:
        """{(u, v): reason} for roads where EVERY parallel edge is a class this vehicle may not use.

        Static (does not depend on time), cached per set of allowed classes.
        """
        allowed = allowed_classes_of(vehicle)
        if allowed not in self._static:
            bad: dict = {}
            ok_pairs = set()
            for (u, v, _k), cls in self._class.items():
                if cls in allowed:
                    ok_pairs.add((u, v))
                elif (u, v) not in bad:
                    bad[(u, v)] = f"KR-3 road class '{cls}' not allowed"
            self._static[allowed] = {e: r for e, r in bad.items() if e not in ok_pairs}
        return self._static[allowed]

    def zone_blocked(self, vehicle, t: float) -> dict:
        """{(u, v): (reason, until)}: roads INTO a zone closed to this vehicle class at time t."""
        vclass = class_of(vehicle)
        out: dict = {}
        for z in self.zones:
            if not z.restricts(vclass, t):
                continue
            for node in z.nodes:
                if node in self.G:
                    for u in self.G.predecessors(node):
                        out[(u, node)] = (f"KR-6 zone {z.id} closed to {vclass} vehicles", z.end)
        return out

    def blocked_edges(self, vehicle, t: float = SIM_START_S) -> dict:
        """{(u, v): reason}: every road this vehicle may not enter at time t (KR-3, KR-6, KR-4)."""
        out = dict(self.class_blocked(vehicle))
        out.update({e: r for e, (r, _until) in self.zone_blocked(vehicle, t).items()})
        if self.is_blocked is not None:
            for u, v in set(self.G.edges()):
                if (u, v) not in out and self.is_blocked(u, v, t):
                    out[(u, v)] = "KR-4 edge closed"
        return out

    # ------------------------------------------------------------ for R2's searches
    def cost_fn(self, vehicle, base_cost_fn: Optional[Callable] = None, t: float = SIM_START_S):
        """cost_fn(u, v, data) for astar / dijkstra / yen / TravelTimeMatrix: inf if forbidden.

        Checks each parallel edge separately (the searches call cost_fn once per parallel edge).
        """
        base = base_cost_fn or _free_flow_cost
        zones, closed = self.zones, self.is_blocked

        def cost(u, v, data):
            ok, _ = road_allowed(vehicle, u, v, data, t, zones, closed)
            return base(u, v, data) if ok else INF

        return cost

    def cost_fn_factory(self, vehicle, base_factory: Optional[Callable] = None):
        """factory(t) -> cost_fn for R2's TravelTimeMatrix(G, factory)."""

        def factory(t):
            return self.cost_fn(vehicle, base_factory(t) if base_factory else None, t)

        return factory

    # ------------------------------------------------------------ for R7 and R4
    def view(self, world, vehicle) -> "VehicleWorldView":
        return VehicleWorldView(world, vehicle, self)

    def explain_edge(self, vehicle, u, v, t: float = SIM_START_S) -> str:
        """Why u -> v is or is not usable for this vehicle (for logs and the viva demo)."""
        reason = self.blocked_edges(vehicle, t).get((u, v))
        return reason or "ok"


class VehicleWorldView:
    """R1's World as one vehicle may use it: rule-forbidden roads look closed.

    Delegates everything to the real world; only is_blocked, edge_time and cost_fn_at change.
    is_blocked(u, v, t, key=None) follows R1's convention (key None = the fastest road u -> v).
    """

    def __init__(self, world, vehicle, rules: RoadRules):
        self._world, self._vehicle, self._rules = world, vehicle, rules

    def __getattr__(self, name):
        return getattr(self._world, name)

    def rule_blocked(self, u, v, t: float, key=None) -> bool:
        if key is None:
            key = self._world.edge_key(u, v)
        return not self._rules.edge_allowed(self._vehicle, u, v, key, t)[0]

    def is_blocked(self, u, v, t: float, key=None) -> bool:
        return self._world.is_blocked(u, v, t, key) or self.rule_blocked(u, v, t, key)

    def edge_time(self, u, v, t: float, key=None) -> float:
        return INF if self.rule_blocked(u, v, t, key) else self._world.edge_time(u, v, t, key)

    def cost_fn_at(self, t_seconds: float) -> Callable:
        def cost(u, v, data=None) -> float:
            return self.edge_time(u, v, t_seconds)

        return cost


# ---------------------------------------------------------------- KR-13 in the planners
def priority_stops(
    vehicle, orders, travel_time=None, t_now: float = SIM_START_S, end_at_depot: bool = True
):
    """Stop nodes in KR-13 order for one vehicle, plus the rule engine's result.

    Express first; if that breaks a window or the shift end, the engine's KR-13x / KR-13y overrides
    pick another order. If no order is feasible the stops still come back in plain priority order
    (the planner must drive somewhere) and result["feasible"] is False with the reasons.
    Returns (stops, result) where result is run_feasibility_engine's dict.
    """
    orders = list(orders)
    result = run_feasibility_engine(vehicle, orders, travel_time, t_now, check_release=False)
    by_id = {o.id: o for o in orders}
    seq = result["sequence"] or [o.id for o in sort_orders_by_priority(orders)]
    stops: list = []
    for oid in seq:
        node = by_id[oid].node
        if node not in stops:
            stops.append(node)
    if end_at_depot and (not stops or stops[-1] != vehicle.depot_node):
        stops.append(vehicle.depot_node)
    return stops, result


# ---------------------------------------------------------------- explanation trace in the run log
def log_kr_trace(sink, t: float, vehicle_id: str, result: dict, context: str = "") -> dict:
    """Write one "kr_check" row through R1's env.log_event / logger.log (same JSONL rows).

    sink: R1's DeliverySimEnvironment (log_event), R4's sim runner (log_event) or a MetricsLogger.
    TODO(R1): add "kr_check" to docs/log_schema.md (agent_id = vehicle).
    """
    payload = {
        "feasible": bool(result["feasible"]),
        "violated": list(result.get("violated", [])),
        "sequence": list(result.get("sequence", [])),
        "trace": list(result.get("trace", [])),
        "context": context,
    }
    if hasattr(sink, "log_event"):
        sink.log_event("kr_check", payload, vehicle_id)
    else:
        sink.log("kr_check", t, payload, vehicle_id)
    return payload


def zones_from_config(cfg: dict) -> list:
    """KR-6 zones from a scenario config.

    cfg["kr_zones"] = [{id, nodes, start, end, banned_classes}]

    TODO(R2): which areas of Secunderabad are restricted, and their hours.
    """
    out = []
    for z in cfg.get("kr_zones", []) or []:
        out.append(
            Zone(
                str(z["id"]),
                frozenset(int(n) for n in z["nodes"]),
                frozenset(z.get("banned_classes", ["large"])),
                float(z["start"]),
                float(z["end"]),
            )
        )
    return out


LARGE_VEHICLE_CLASSES = sorted(
    {"motorway", "trunk", "primary", "secondary", "tertiary"} - NARROW_ROAD_CLASSES
)

# Hooks for the owners (one line each, see docs/kr_planner_integration.md):
#   TODO(R7): in AgentPlanner.register, build the agent on rules.view(self.env.world, vehicle)
#             and, when stops is None, use priority_stops(vehicle, orders, travel, t)[0].
#   TODO(R4): WorldTravel(rules.view(world, vehicle), now), or rules.cost_fn for its graph.
#   TODO(R1): build RoadRules(world.graph(), zones_from_config(cfg)) in run.py and pass it to
#             the planners; events._emit_new_order -> OrderSampler.generate_order (Week 2).