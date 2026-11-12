"""Agent replanning on world change (R7, Weeks 4 and 5).

Each vehicle is an agent with its own multi-stop D* Lite planner
(src/search/multi_stop.py, one D* Lite per leg). When the world changes
(a closure or a traffic spike from R1's event stream), every agent:

1. works out where it really is (a vehicle on a road cannot turn back, so it
   plans from the end of that road);
2. updates only the roads that changed, using the road-status feed of
   decision D10 (predicted time x live spike multiplier, inf while closed);
3. lets D* Lite repair its route, and gets a new Route with planned ETAs.

Week 5 adds three things:

* Hysteresis: a vehicle only switches route if the new one is clearly
  better, by at least max(min_gain_s, min_gain_frac x old cost). A blocked
  old route (inf) always switches. This stops vehicles flipping between two
  nearly equal routes on every small traffic spike.
* Unreachable stops: if a closure cuts a stop off, its orders are offered to
  ``reassign`` (R4's hook, when it exists) and otherwise marked failed
  (reason ``unreachable``); the vehicle then replans through the stops it can
  still reach. ``unreachable="wait"`` keeps the Week 4 behaviour instead.
* R5's trigger after every local replan (full mode): first every agent
  replans for the event, then the coordination hook runs once per replanned
  vehicle, with everyone's new routes. A vehicle that loses a negotiation and
  detours (``yield_road``) replans once more, but that replan never calls the
  hook again: no double replans. See src/sim/coordination_hook.py.

Modes (decision on conditions, plan section 7.1):

* ``independent``: replan locally and never negotiate (the lower-bound
  baseline). No negotiation messages are ever sent.
* ``full``: the same local replanning, then the coordination hook (R5's
  trigger and negotiation) is called after every replan, but only while
  ``trigger_enabled`` is on.
* ``centralized`` is R4's OR-Tools re-solve; agents do not replan.

Nothing in R1's environment changes: the planner listens through
``env.subscribe``. Use:

    planner = AgentPlanner(env, mode="independent", heuristic=make_heuristic(G))
    planner.register(vehicle, orders)     # sets vehicle.remaining_route
    env.add_vehicle(vehicle, orders)
    env.run()
    planner.finish()                      # logs a replan_summary row
"""

import logging
import math
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from src.search.sim_replanner import VehicleReplanner, stops_from_route, world_cost
from src.sim.interfaces import Planner, Route

logger = logging.getLogger(__name__)

INF = math.inf
MODES = ("independent", "full", "centralized")
UNREACHABLE_POLICIES = ("fail", "wait")

# Hysteresis defaults (W5). To be fixed on pilot seeds, then frozen (D12).
MIN_GAIN_S = 10.0
MIN_GAIN_FRAC = 0.05

# A coordination hook: hook(vehicle_id, route, routes_by_vehicle, t) -> int,
# the number of negotiation messages it sent.
CoordinationHook = Callable[[str, Route, Dict[str, Route], float], int]
# R4's reassignment hook: reassign(vehicle_id, orders, t) -> orders it took.
ReassignHook = Callable[[str, List[Any], float], Iterable[Any]]


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
    """One vehicle's replanning logic (W4: on_world_change; W5: hysteresis,
    dropping unreachable stops, keeping off a road after a negotiation)."""

    def __init__(self, vehicle, world, stops: Sequence[Any], t_seconds: float,
                 heuristic=None, order_ids: Optional[Sequence[str]] = None,
                 min_gain_s: float = MIN_GAIN_S, min_gain_frac: float = MIN_GAIN_FRAC):
        if min_gain_s < 0 or min_gain_frac < 0:
            raise ValueError("hysteresis margins must be >= 0")
        self.vehicle = vehicle
        self.world = world
        self.heuristic = heuristic
        self.min_gain_s = float(min_gain_s)
        self.min_gain_frac = float(min_gain_frac)
        self.replanner = VehicleReplanner(world, vehicle.current_node, list(stops),
                                          t_seconds, heuristic, order_ids)
        self.route: Optional[Route] = self.replanner.to_route(t_seconds)
        self.planned: List[Any] = list(self.route.nodes)
        if self.planned:                          # the vehicle now drives this route
            vehicle.remaining_route = self.planned[1:]
        self._old_rest: Optional[List[Any]] = None
        self.n_replans = 0
        self.n_kept = 0                           # switches stopped by hysteresis
        self.cpu_seconds = 0.0
        self.last_cpu = 0.0
        self.last_decision: Optional[str] = None  # switched | kept | same | unreachable
        self.last_gain = 0.0                      # old cost - new cost (s)

    # -- where is the vehicle? ------------------------------------------
    def planning_start(self) -> Any:
        """The node a new route must start from (end of the current road)."""
        v = self.vehicle
        return v.current_edge[1] if v.current_edge is not None else v.current_node

    def sync(self) -> Any:
        """Move the planner along the nodes the vehicle has driven since the
        last plan, so legs whose stop was reached are dropped.

        The environment only pops from the front of remaining_route, so it is
        the tail of the last planned path. Returns the planning start. Also
        remembers the rest of the old route from there (for hysteresis).
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
            self._old_rest = planned[start_idx:]
            return planned[start_idx]
        # Route was changed by someone else (or the vehicle is waiting at a
        # node): plan from where it is, same remaining stops.
        start = self.planning_start()
        self.replanner.advance(start)
        self._old_rest = None
        return start

    # -- the W4 entry point ---------------------------------------------
    def on_world_change(self, changes: Iterable[Any], t_seconds: float
                        ) -> Optional[Route]:
        """Update D* Lite for the changed roads and return the new Route.

        ``changes`` are disruption Events (or their payloads, or (u, v) road
        tuples). Returns None if the vehicle keeps its route: nothing it sees
        changed, the best path is the same, or the new one is not better by
        the hysteresis margin (``last_decision`` says which). A Route with no
        nodes means a remaining stop is now unreachable; the vehicle keeps its
        old route until AgentPlanner drops the stop (``drop_stops``).
        """
        cpu0 = time.process_time()
        self.last_decision = None
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
        return self._choose(t_seconds, cpu0)

    def _choose(self, t_seconds: float, cpu0: float, hysteresis: bool = True
                ) -> Optional[Route]:
        """Compare the repaired best path with the old one and decide."""
        planner = self.replanner.planner
        new_path = planner.path()
        if not new_path:
            self.last_decision = "unreachable"
            route = Route([], [], [])
            self.route = route
            self.n_replans += 1
            self._spent(cpu0)
            return route
        old = self._old_rest
        if old and old[-1] == new_path[-1] and new_path == old:
            self.last_decision = "same"            # only the ETAs moved
            self.route = self.replanner.to_route(t_seconds, nodes=old)
            self.cpu_seconds += time.process_time() - cpu0
            return None
        if hysteresis and old and old[-1] == new_path[-1]:
            old_cost = self.replanner.path_cost_of(old)
            new_cost = planner.path_cost()
            self.last_gain = old_cost - new_cost
            margin = max(self.min_gain_s, self.min_gain_frac * old_cost)
            if old_cost < INF and self.last_gain < margin:
                self.last_decision = "kept"
                self.n_kept += 1
                self.route = self.replanner.to_route(t_seconds, nodes=old)
                self._spent(cpu0)
                return None
        else:
            self.last_gain = INF if old else 0.0
        return self._switch(new_path, t_seconds, cpu0)

    def _switch(self, path: List[Any], t_seconds: float, cpu0: float) -> Route:
        route = self.replanner.to_route(t_seconds, nodes=path)
        self.vehicle.remaining_route = list(route.nodes[1:])
        self.planned = list(route.nodes)
        self._old_rest = list(route.nodes)
        self.route = route
        self.last_decision = "switched"
        self.n_replans += 1
        self._spent(cpu0)
        return route

    def _spent(self, cpu0: float) -> None:
        self.last_cpu = time.process_time() - cpu0
        self.cpu_seconds += self.last_cpu

    @property
    def unreachable_stops(self) -> List[Any]:
        return self.replanner.planner.unreachable_stops()

    @property
    def remaining_stops(self) -> List[Any]:
        return list(self.replanner.planner.remaining_stops)

    # -- W5: unreachable stops ------------------------------------------
    def drop_stops(self, stops: Iterable[Any], t_seconds: float) -> Route:
        """Give up on these stops and plan through the rest.

        A fresh multi-stop D* Lite is built from the planning start (rare, so
        a full search is fine). If dropping a stop leaves another stop cut
        off, that one is dropped too. Returns the new Route; ``dropped`` lists
        every stop given up, in order.
        """
        cpu0 = time.process_time()
        old = self.replanner
        drop = set(stops)
        self.dropped: List[Any] = []
        start = self.planning_start()
        while True:
            keep = [s for s in old.planner.remaining_stops if s not in drop]
            self.dropped = [s for s in old.planner.remaining_stops if s in drop]
            ids = [old.order_ids.get(s) for s in keep]
            fresh = VehicleReplanner(self.world, start, keep, t_seconds,
                                     self.heuristic, ids)
            fresh.watched |= old.watched
            fresh.avoid = dict(old.avoid)
            fresh.refresh(t_seconds)
            cut = fresh.planner.unreachable_stops()
            if not cut:
                break
            drop |= set(cut)
        self.replanner = fresh
        path = fresh.planner.path()
        return self._switch(path, t_seconds, cpu0)

    # -- W5: keep off a road after losing a negotiation ------------------
    def avoid_road(self, u: Any, v: Any, until_t: float, t_seconds: float
                   ) -> Optional[Route]:
        """Replan around road u -> v until until_t (a detour, no hysteresis).

        Returns the new Route, or None (and forgets the request) if there is
        no way round or the route does not use that road.
        """
        cpu0 = time.process_time()
        self.last_decision = None
        if self.replanner.planner.done:
            return None
        self.sync()
        rest = self._old_rest or self.planned
        if (u, v) not in set(zip(rest, rest[1:])):
            return None
        self.replanner.avoid[(u, v)] = until_t
        self.replanner.watched.add((u, v))
        self.replanner.refresh(t_seconds)
        path = self.replanner.planner.path()
        if not path:
            del self.replanner.avoid[(u, v)]
            self.replanner.refresh(t_seconds)
            self.cpu_seconds += time.process_time() - cpu0
            return None
        return self._switch(path, t_seconds, cpu0)

    def detour_extra(self, u: Any, v: Any) -> float:
        """Extra seconds if this vehicle had to keep off u -> v (inf: no way
        round). The planner is left exactly as it was."""
        planner = self.replanner.planner
        if planner.done:
            return 0.0
        try:
            cost = planner.edge_cost(u, v)
        except (KeyError, ValueError):
            return 0.0
        before = planner.path_cost()
        planner.update_edge_cost(u, v, INF)
        after = planner.path_cost()
        planner.update_edge_cost(u, v, cost)
        return after - before


class AgentPlanner(Planner):
    """Fleet of replanning agents attached to R1's DeliverySimEnvironment."""

    def __init__(self, env, mode: str = "independent", heuristic=None,
                 coordination: Optional[CoordinationHook] = None,
                 trigger_enabled: Optional[bool] = None,
                 unreachable: str = "fail",
                 reassign: Optional[ReassignHook] = None,
                 min_gain_s: float = MIN_GAIN_S,
                 min_gain_frac: float = MIN_GAIN_FRAC):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        if mode == "centralized":
            raise ValueError("centralized mode is R4's re-solver; agents do not replan")
        if unreachable not in UNREACHABLE_POLICIES:
            raise ValueError(f"unreachable must be one of {UNREACHABLE_POLICIES}")
        if mode == "full" and coordination is None:
            logger.warning("full mode without a coordination hook: behaves as independent")
        self.env = env
        self.mode = mode
        self.heuristic = heuristic
        self.coordination = coordination
        self.unreachable = unreachable
        self.reassign = reassign
        self.min_gain_s = min_gain_s
        self.min_gain_frac = min_gain_frac
        self.trigger_enabled = (mode == "full") if trigger_enabled is None else trigger_enabled
        if mode == "independent" and self.trigger_enabled:
            raise ValueError("independent mode never negotiates: trigger_enabled must be off")
        self.agents: Dict[str, ReplanningAgent] = {}
        self.negotiation_messages = 0
        self.negotiation_calls = 0
        self.yields = 0
        self.failed_unreachable: List[str] = []
        self.reassigned: List[str] = []
        self._coordinating = False
        if hasattr(coordination, "bind"):
            coordination.bind(self)
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
        agent = ReplanningAgent(vehicle, self.env.world, stops, t, self.heuristic, order_ids,
                                self.min_gain_s, self.min_gain_frac)
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
        return {vid: a.route for vid, a in self.agents.items()
                if a.route is not None and a.route.nodes}

    def pending_orders(self, vid: str) -> List[Any]:
        """The vehicle's undelivered orders in R1's environment."""
        return list(getattr(self.env, "_pending", {}).get(vid, []))

    # -- events ----------------------------------------------------------
    def on_event(self, event) -> None:
        if event.event_type != "disruption":
            return
        # 1. every agent replans once for this event ...
        replanned: List[Tuple[str, Route]] = []
        for vid, agent in self.agents.items():
            start = agent.planning_start()
            route = agent.on_world_change([event], event.t)
            if agent.last_decision == "kept":
                self.env.log_event("replan_kept", {
                    "trigger": event.payload.get("type"),
                    "edge": list(event.payload["edge"][:2]),
                    "gain_s": round(agent.last_gain, 3),
                    "cpu_seconds": agent.last_cpu,
                    "mode": self.mode,
                }, agent_id=vid)
            if route is None:
                continue
            self._log_replan(vid, agent, route, start, event.payload.get("type"),
                             list(event.payload["edge"][:2]))
            if not route.nodes and self.unreachable == "fail":
                route = self._handle_unreachable(vid, agent, event.t)
            if route.nodes:
                replanned.append((vid, route))
        # 2. ... then R5's trigger once per replanned vehicle, on the new routes
        for vid, route in replanned:
            self._after_replan(vid, route, event.t)

    def _log_replan(self, vid, agent, route, start, trigger, edge) -> None:
        self.env.log_event("replan", {
            "trigger": trigger,
            "edge": edge,
            "from_node": route.nodes[0] if route.nodes else start,
            "route_found": bool(route.nodes),
            "unreachable_stops": agent.unreachable_stops,
            "expanded": agent.replanner.planner.expanded,
            "cpu_seconds": agent.last_cpu,
            "gain_s": None if math.isinf(agent.last_gain) else round(agent.last_gain, 3),
            "mode": self.mode,
            "trigger_enabled": self.trigger_enabled,
        }, agent_id=vid)

    def _handle_unreachable(self, vid: str, agent: ReplanningAgent, t: float) -> Route:
        """Offer the cut-off orders to R4, fail the rest, plan through the
        stops that are still reachable."""
        stops = agent.unreachable_stops
        start = agent.planning_start()
        route = agent.drop_stops(stops, t)
        dropped = set(agent.dropped)
        orders = [o for o in self.pending_orders(vid) if o.node in dropped]
        taken = set()
        if orders and self.reassign is not None:
            taken = {o.id for o in (self.reassign(vid, list(orders), t) or ())}
        pending = getattr(self.env, "_pending", {}).get(vid)
        failed, reassigned = [], []
        for o in orders:
            if pending is not None and o in pending:
                pending.remove(o)
            if o.id in taken:
                reassigned.append(o.id)
            else:
                failed.append(o.id)
                fail = getattr(self.env, "_fail", None)
                if fail is not None:
                    fail(agent.vehicle, o, "unreachable")
        self.failed_unreachable.extend(failed)
        self.reassigned.extend(reassigned)
        self.env.log_event("stop_unreachable", {
            "stops": list(agent.dropped),
            "failed": failed,
            "reassigned": reassigned,
        }, agent_id=vid)
        self._log_replan(vid, agent, route, start, "unreachable", None)
        return route

    def _after_replan(self, vid: str, route: Route, t: float) -> None:
        """Independent mode stops here. Full mode calls R5's hook, once per
        local replan, and never for a replan the hook itself caused."""
        if (not self.trigger_enabled or self.coordination is None or not route.nodes
                or self._coordinating):
            return
        self.negotiation_calls += 1
        self._coordinating = True
        try:
            sent = int(self.coordination(vid, route, self.routes(), t) or 0)
        finally:
            self._coordinating = False
        self.negotiation_messages += sent

    # -- W5: called by the coordination hook ----------------------------
    def yield_road(self, vid: str, u: Any, v: Any, until_t: float, t: float,
                   reason: str = "negotiation_yield") -> bool:
        """vid lost a negotiation for road u -> v: detour until until_t.

        The detour is logged as a ``replan`` row (trigger = reason) and does
        not call the coordination hook again (no double replans). Returns
        False if there is no way round (the vehicle keeps its route).
        """
        agent = self.agents.get(vid)
        if agent is None:
            return False
        start = agent.planning_start()
        route = agent.avoid_road(u, v, until_t, t)
        if route is None:
            return False
        self.yields += 1
        self._log_replan(vid, agent, route, start, reason, [u, v])
        return True

    # -- end of run ------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        cpu = [a.cpu_seconds for a in self.agents.values()]
        return {
            "mode": self.mode,
            "trigger_enabled": self.trigger_enabled,
            "replans": sum(a.n_replans for a in self.agents.values()),
            "replans_kept": sum(a.n_kept for a in self.agents.values()),
            "replan_cpu_seconds": sum(cpu),
            "negotiation_calls": self.negotiation_calls,
            "negotiation_messages": self.negotiation_messages,
            "yields": self.yields,
            "failed_unreachable": list(self.failed_unreachable),
            "reassigned": list(self.reassigned),
            "unreachable_stops": {vid: a.unreachable_stops for vid, a in self.agents.items()
                                  if a.unreachable_stops},
            "min_gain_s": self.min_gain_s,
            "min_gain_frac": self.min_gain_frac,
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


__all__ = ["AgentPlanner", "ReplanningAgent", "MODES", "MIN_GAIN_S", "MIN_GAIN_FRAC",
           "snapshot_cost"]
