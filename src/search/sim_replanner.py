"""D* Lite replanning for R1's simulator (R7, Week 3).

Two pieces, neither edits R1's files:

* VehicleReplanner: one vehicle's multi-stop D* Lite planner fed with costs
  from R1's World (D10: predicted travel time plus the live road-status feed
  of closures and spikes; a closed road costs inf).
* SimReplanner: subscribes to DeliverySimEnvironment events. When a closure
  or spike happens, every registered vehicle's planner is updated and its
  remaining_route is replaced with the new D* Lite route. A vehicle in the
  middle of a road cannot turn back, so it replans from the end of that road.

    replanner = SimReplanner(env, heuristic=make_heuristic(world.graph()))
    replanner.register(vehicle, stops=[order.node for order in orders])
    env.run()

See src/search/README.md for the 5-line change that replaces the
"wait 60 s" TODO(R7) in environment.py with reroute().
"""

import logging
import math
import time

from src.search.multi_stop import MultiStopPlanner

logger = logging.getLogger(__name__)
INF = math.inf


def world_cost(world, u, v, t_seconds):
    """Cost of road u -> v at time t as an agent sees it (decision D10).

    Predicted travel time x live spike multiplier, inf if closed. The
    cheapest open parallel road is used. It is never below free-flow time
    (R6's multipliers and spikes are >= 1), so R2's heuristic stays valid.
    """
    best = INF
    predicted = None
    for key in world.graph()[u][v]:
        if world.is_blocked(u, v, key, t_seconds):
            continue
        if predicted is None:
            predicted = world.predicted_time(u, v, t_seconds)
        best = min(best, predicted * world.spike_multiplier(u, v, key, t_seconds))
    return best


def world_adjacency(world, t_seconds):
    """{u: {v: cost}} for the whole road graph at time t."""
    G = world.graph()
    adj = {u: {} for u in G.nodes}
    for u, v in set(G.edges()):
        adj[u][v] = world_cost(world, u, v, t_seconds)
    return adj


def stops_from_route(route, must_visit):
    """Stops to keep when rerouting a node route.

    The nodes of route that are in must_visit (first time each is reached),
    in route order, plus the route's last node (for example the depot).
    """
    stops = []
    for node in route:
        if node in must_visit and node not in stops:
            stops.append(node)
    if route and (not stops or stops[-1] != route[-1]):
        stops.append(route[-1])
    return stops


class VehicleReplanner:
    """Multi-stop D* Lite for one vehicle, kept in step with the World."""

    def __init__(self, world, start, stops, t_seconds, heuristic=None,
                 order_ids=None):
        self.world = world
        self.order_ids = dict(zip(stops, order_ids)) if order_ids else {}
        self.planner = MultiStopPlanner(
            world_adjacency(world, t_seconds), start, stops, heuristic)
        # Roads with a closure or spike: their cost can change again when it
        # ends, and no event announces that, so they are re-checked.
        self.watched = set()
        for u, v, _ in list(world.closures) + list(world.spikes):
            self.watched.add((u, v))
        self.replans = 0

    @property
    def position(self):
        return self.planner.position

    def refresh(self, t_seconds, edges=None):
        """Re-read World costs for these roads (default: watched roads).

        Returns how many costs changed.
        """
        changed = 0
        for u, v in (self.watched if edges is None else edges):
            if not self.planner.legs:
                break
            cost = world_cost(self.world, u, v, t_seconds)
            if cost != self.planner.edge_cost(u, v):
                self.planner.update_edge_cost(u, v, cost)
                changed += 1
        return changed

    def road_changed(self, u, v, t_seconds):
        """A closure or spike started on u -> v (from the event feed)."""
        self.watched.add((u, v))
        return self.refresh(t_seconds)

    def advance(self, node):
        """The vehicle has reached node (or will, if it is on a road to it)."""
        self.planner.move_start(node)

    def path(self):
        """Node path from the current position through all remaining stops."""
        self.replans += 1
        return self.planner.path()

    def to_route(self, t_seconds):
        """R1's Route: nodes, planned ETA at each node, order id or None."""
        from src.sim.interfaces import Route
        nodes = self.path()
        times, order_ids = [], []
        t = t_seconds
        goals = list(self.planner.remaining_stops)
        for i, node in enumerate(nodes):
            if i > 0:
                t += self.planner.legs[0].graph[nodes[i - 1]][node]
            times.append(t)
            if goals and node == goals[0]:
                order_ids.append(self.order_ids.get(goals.pop(0)))
            else:
                order_ids.append(None)
        return Route(nodes, times, order_ids)


def reroute(world, vehicle, stops, t_seconds, heuristic=None):
    """One-off reroute: new remaining_route for vehicle, or None if impossible.

    Plans from vehicle.current_node through stops, in order, with the World's
    costs at t_seconds. The returned list excludes the current node, as
    Vehicle.remaining_route does. None means a stop cannot be reached now.
    """
    planner = VehicleReplanner(world, vehicle.current_node, stops, t_seconds,
                               heuristic)
    path = planner.path()
    if not path:
        return None
    return path[1:]


class SimReplanner:
    """Reroutes registered vehicles when the World changes (independent mode).

    Uses R1's DeliverySimEnvironment.subscribe hook, so R1's code is
    unchanged. Each reroute is logged as a "replan" event with its CPU time
    (time.process_time, decision D9) and the number of nodes expanded.
    """

    def __init__(self, env, heuristic=None):
        self.env = env
        self.heuristic = heuristic
        self.vehicles = {}          # id -> (vehicle, VehicleReplanner, planned)
        env.subscribe(self.on_event)

    def register(self, vehicle, stops, order_ids=None):
        """Plan the vehicle's route through stops and set remaining_route."""
        t = self.env.get_current_time()
        vr = VehicleReplanner(self.env.world, vehicle.current_node, stops, t,
                              self.heuristic, order_ids)
        path = vr.path()
        if path:
            vehicle.remaining_route = path[1:]
        self.vehicles[vehicle.id] = (vehicle, vr, path)
        return path

    def _sync(self, vehicle, vr, planned):
        """Move the planner to where the vehicle is in its planned path.

        remaining_route is a suffix of the planned path (the environment only
        pops from its front). A vehicle on a road cannot turn back, so its
        planning start is the end of that road.
        """
        rest = list(vehicle.remaining_route)
        if vehicle.current_edge is not None:
            rest = [vehicle.current_edge[1]] + rest
        n = len(planned)
        if not planned or len(rest) >= n or planned[n - len(rest):] != rest:
            # Not our route any more (or the vehicle is waiting on a road it
            # already popped): plan from where it is, same remaining stops.
            start = (vehicle.current_edge[1] if vehicle.current_edge
                     else vehicle.current_node)
            vr.advance(start)
            return start
        start_idx = n - len(rest) - 1
        if vehicle.current_edge is not None:
            start_idx += 1
        for node in planned[1:start_idx + 1]:
            vr.advance(node)
        return planned[start_idx]

    def on_event(self, event):
        if event.event_type != "disruption":
            return
        u, v, _key = event.payload["edge"]
        for vid, (vehicle, vr, planned) in list(self.vehicles.items()):
            if vr.planner.done:
                continue
            cpu0 = time.process_time()
            start = self._sync(vehicle, vr, planned)
            changed = vr.road_changed(u, v, event.t)
            if not changed:
                continue
            path = vr.path()
            cpu = time.process_time() - cpu0
            if path:
                vehicle.remaining_route = path[1:]
                self.vehicles[vid] = (vehicle, vr, path)
            self.env.log_event("replan", {
                "trigger": event.payload.get("type"),
                "edge": [u, v],
                "from_node": start,
                "route_found": bool(path),
                "unreachable_stops": vr.planner.unreachable_stops(),
                "expanded": vr.planner.expanded,
                "cpu_seconds": cpu,
            }, agent_id=vid)
