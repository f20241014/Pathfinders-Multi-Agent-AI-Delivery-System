"""Agent replanning on world change (R7, Week 4).

Each vehicle is an agent with its own multi-stop D* Lite planner
(src/search/multi_stop.py, one D* Lite per leg). When the world changes
(a closure or a traffic spike from R1's event stream), every agent:

1. works out where it really is (a vehicle on a road cannot turn back, so it
   plans from the end of that road);
2. updates only the roads that changed, using the road-status feed of
   decision D10 (predicted time x live spike multiplier, inf while closed);
3. lets D* Lite repair its route, and gets a new Route with planned ETAs.

Modes (decision on conditions, plan section 7.1):

* ``independent``: replan locally and never negotiate (the lower-bound
  baseline). No negotiation messages are ever sent.
* ``full``: the same local replanning, then the coordination hook (R5's
  trigger and negotiation) is called after every replan, but only while
  ``trigger_enabled`` is on.
* ``centralized`` is R4's OR-Tools re-solve; agents do not replan.

``trigger_enabled`` can be switched at run time (``set_trigger_enabled``),
for example to compare full and independent behaviour within one scenario.

Nothing in R1's environment changes: the planner listens through
``env.subscribe``. Use:

    planner = AgentPlanner(env, mode="independent", heuristic=make_heuristic(G))
    planner.register(vehicle, orders)     # sets vehicle.remaining_route
    env.add_vehicle(vehicle, orders)
    env.run()
    planner.finish()                      # logs a replan_summary row
"""

import logging
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from src.search.sim_replanner import VehicleReplanner, stops_from_route, world_cost
from src.sim.interfaces import Planner, Route

logger = logging.getLogger(__name__)

MODES = ("independent", "full", "centralized")

# A coordination hook: hook(vehicle_id, route, routes_by_vehicle, t) -> int,
# the number of negotiation messages it sent (R5 plugs in here in Week 5).
CoordinationHook = Callable[[str, Route, Dict[str, Route], float], int]


def _road_of(change: Any) -> Optional[Tuple[Any, Any]]:
    """(u, v) from an Event, a payload dict, or a (u, v[, key]) tuple."""
    payload = getattr(change, "payload", change)
    if isinstance(payload, dict):
        edge = payload.get("edge")
        if edge is None:
            return None
        return edge[0], edge[1]
    if isinstance(change, (tuple, list)) and len(change) >= 2:
        return change[0], change[1]
    return None


class ReplanningAgent:
    """One vehicle's replanning logic (W4: on_world_change)."""

    def __init__(self, vehicle, world, stops: Sequence[Any], t_seconds: float,
                 heuristic=None, order_ids: Optional[Sequence[str]] = None):
        self.vehicle = vehicle
        self.world = world
        self.replanner = VehicleReplanner(world, vehicle.current_node, list(stops),
                                          t_seconds, heuristic, order_ids)
        self.route: Optional[Route] = self.replanner.to_route(t_seconds)
        self.planned: List[Any] = list(self.route.nodes)
        if self.planned:                          # the vehicle now drives this route
            vehicle.remaining_route = self.planned[1:]
        self.n_replans = 0
        self.cpu_seconds = 0.0
        self.last_cpu = 0.0

    # -- where is the vehicle? ------------------------------------------
    def planning_start(self) -> Any:
        """The node a new route must start from (end of the current road)."""
        v = self.vehicle
        return v.current_edge[1] if v.current_edge is not None else v.current_node

    def sync(self) -> Any:
        """Move the planner along the nodes the vehicle has driven since the
        last plan, so legs whose stop was reached are dropped.

        The environment only pops from the front of remaining_route, so it is
        the tail of the last planned path. Returns the planning start.
        """
        rest = list(self.vehicle.remaining_route)
        if self.vehicle.current_edge is not None:
            rest = [self.vehicle.current_edge[1]] + rest
        planned = self.planned
        n = len(planned)
        if planned and len(rest) < n and planned[n - len(rest):] == rest:
            start_idx = n - len(rest) - 1
            if self.vehicle.current_edge is not None:
                start_idx += 1
            for node in planned[1:start_idx + 1]:
                self.replanner.advance(node)
            return planned[start_idx]
        # Route was changed by someone else (or the vehicle is waiting at a
        # node): plan from where it is, same remaining stops.
        start = self.planning_start()
        self.replanner.advance(start)
        return start

    # -- the W4 entry point ---------------------------------------------
    def on_world_change(self, changes: Iterable[Any], t_seconds: float
                        ) -> Optional[Route]:
        """Update D* Lite for the changed roads and return the new Route.

        ``changes`` are disruption Events (or their payloads, or (u, v) road
        tuples). Returns None if no cost the agent sees has changed (no new
        route needed). A Route with no nodes means a remaining stop is now
        unreachable; the vehicle keeps its old route (W5: mark failed or ask
        R4 to reassign).
        """
        cpu0 = time.process_time()
        if self.replanner.planner.done:
            return None
        self.sync()
        roads = [r for r in (_road_of(c) for c in changes) if r is not None]
        for road in roads:
            self.replanner.watched.add(road)
        changed = self.replanner.refresh(t_seconds)
        if not changed:
            self.cpu_seconds += time.process_time() - cpu0
            return None
        route = self.replanner.to_route(t_seconds)
        if route.nodes:
            self.vehicle.remaining_route = list(route.nodes[1:])
            self.planned = list(route.nodes)
        self.route = route
        self.n_replans += 1
        self.last_cpu = time.process_time() - cpu0
        self.cpu_seconds += self.last_cpu
        return route

    @property
    def unreachable_stops(self) -> List[Any]:
        return self.replanner.planner.unreachable_stops()


class AgentPlanner(Planner):
    """Fleet of replanning agents attached to R1's DeliverySimEnvironment."""

    def __init__(self, env, mode: str = "independent", heuristic=None,
                 coordination: Optional[CoordinationHook] = None,
                 trigger_enabled: Optional[bool] = None):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        if mode == "centralized":
            raise ValueError("centralized mode is R4's re-solver; agents do not replan")
        if mode == "full" and coordination is None:
            logger.warning("full mode without a coordination hook: behaves as independent")
        self.env = env
        self.mode = mode
        self.heuristic = heuristic
        self.coordination = coordination
        self.trigger_enabled = (mode == "full") if trigger_enabled is None else trigger_enabled
        if mode == "independent" and self.trigger_enabled:
            raise ValueError("independent mode never negotiates: trigger_enabled must be off")
        self.agents: Dict[str, ReplanningAgent] = {}
        self.negotiation_messages = 0
        self.negotiation_calls = 0
        env.subscribe(self.on_event)

    # -- runtime toggle --------------------------------------------------
    def set_trigger_enabled(self, enabled: bool) -> None:
        """Switch coordination on or off during a run (full mode only)."""
        if self.mode == "independent" and enabled:
            raise ValueError("independent mode never negotiates")
        self.trigger_enabled = bool(enabled)
        self.env.log_event("trigger_toggle", {"trigger_enabled": self.trigger_enabled})

    # -- setup -----------------------------------------------------------
    def register(self, vehicle, orders: Sequence[Any] = (), stops: Optional[Sequence[Any]] = None
                 ) -> Route:
        """Plan the vehicle's route through its stops; sets remaining_route.

        Stops default to the order nodes, in the order the vehicle's current
        route visits them (then any not on it), ending at the route's last
        node (for example the depot) if it has one.
        """
        orders = list(orders)
        if stops is None:
            nodes = [o.node for o in orders]
            stops = stops_from_route(list(vehicle.remaining_route), set(nodes))
            for n in nodes:
                if n not in stops:
                    stops.insert(len(stops) - (1 if vehicle.remaining_route else 0), n)
        ids_by_node = {}
        for o in orders:
            ids_by_node.setdefault(o.node, o.id)
        order_ids = [ids_by_node.get(s) for s in stops]
        t = self.env.get_current_time()
        agent = ReplanningAgent(vehicle, self.env.world, stops, t, self.heuristic, order_ids)
        self.agents[vehicle.id] = agent
        return agent.route

    def plan(self, vehicles: List[Any], orders: List[Any]) -> Dict[str, Route]:
        """Planner interface: a Route per vehicle through the order nodes on
        its current route (orders are matched to vehicles by route node)."""
        routes = {}
        for vehicle in vehicles:
            mine = [o for o in orders
                    if o.node in vehicle.remaining_route or o.node == vehicle.current_node]
            routes[vehicle.id] = self.register(vehicle, mine)
        return routes

    def routes(self) -> Dict[str, Route]:
        return {vid: a.route for vid, a in self.agents.items() if a.route is not None}

    # -- events ----------------------------------------------------------
    def on_event(self, event) -> None:
        if event.event_type != "disruption":
            return
        for vid, agent in self.agents.items():
            start = agent.planning_start()
            route = agent.on_world_change([event], event.t)
            if route is None:
                continue
            self.env.log_event("replan", {
                "trigger": event.payload.get("type"),
                "edge": list(event.payload["edge"][:2]),
                "from_node": route.nodes[0] if route.nodes else start,
                "route_found": bool(route.nodes),
                "unreachable_stops": agent.unreachable_stops,
                "expanded": agent.replanner.planner.expanded,
                "cpu_seconds": agent.last_cpu,
                "mode": self.mode,
                "trigger_enabled": self.trigger_enabled,
            }, agent_id=vid)
            self._after_replan(vid, route, event.t)

    def _after_replan(self, vid: str, route: Route, t: float) -> None:
        """Independent mode stops here. Full mode calls R5's hook (W5)."""
        if not self.trigger_enabled or self.coordination is None or not route.nodes:
            return
        self.negotiation_calls += 1
        sent = int(self.coordination(vid, route, self.routes(), t) or 0)
        self.negotiation_messages += sent

    # -- end of run ------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        cpu = [a.cpu_seconds for a in self.agents.values()]
        return {
            "mode": self.mode,
            "trigger_enabled": self.trigger_enabled,
            "replans": sum(a.n_replans for a in self.agents.values()),
            "replan_cpu_seconds": sum(cpu),
            "negotiation_calls": self.negotiation_calls,
            "negotiation_messages": self.negotiation_messages,
            "unreachable_stops": {vid: a.unreachable_stops for vid, a in self.agents.items()
                                  if a.unreachable_stops},
        }

    def finish(self) -> Dict[str, Any]:
        """Log a replan_summary row (call after env.run)."""
        s = self.summary()
        self.env.log_event("replan_summary", s)
        return s


def snapshot_cost(world, t_seconds: float):
    """cost_fn(u, v, data) with the same D10 costs agents see, for tests and
    for comparing against a fresh A*."""
    def cost(u, v, data=None):
        return world_cost(world, u, v, t_seconds)
    return cost


__all__ = ["AgentPlanner", "ReplanningAgent", "MODES", "snapshot_cost"]
