"""D* Lite replanning for R1's simulator (R7, Week 3).

Two pieces, neither edits R1's files:

* VehicleReplanner: one vehicle's multi-stop D* Lite planner fed with costs
  from R1's World (D10: predicted travel time plus the live road-status feed
  of closures and spikes; a closed road costs inf).
* reroute(): a one-off new route, for the wait loop in environment.py.

The fleet-level event handling (formerly SimReplanner) is
src/sim/agent_planner.py: AgentPlanner. SimReplanner is kept as a name for it.

See src/search/README.md for the 5-line change that replaces the
"wait 60 s" TODO(R7) in environment.py with reroute().
"""

import logging
import math

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
        if world.is_blocked(u, v, t_seconds, key):
            continue
        if predicted is None:
            predicted = world.predicted_time(u, v, t_seconds)
        best = min(best, predicted * world.spike_multiplier(u, v, t_seconds, key))
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
        self.stops = list(stops)
        self.heuristic = heuristic
        self.planner = MultiStopPlanner(
            world_adjacency(world, t_seconds), start, stops, heuristic)
        # Roads with a closure or spike: their cost can change again when it
        # ends, and no event announces that, so they are re-checked.
        self.watched = set()
        for u, v, _ in list(world.closures) + list(world.spikes):
            self.watched.add((u, v))
        # Roads this vehicle agreed to keep off until a time (it lost a
        # negotiation, Week 5): (u, v) -> until t. They cost inf until then.
        self.avoid = {}
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
            cost = self.cost(u, v, t_seconds)
            if cost != self.planner.edge_cost(u, v):
                self.planner.update_edge_cost(u, v, cost)
                changed += 1
        return changed

    def cost(self, u, v, t_seconds):
        """World cost (D10), or inf while this vehicle is keeping off u -> v."""
        until = self.avoid.get((u, v))
        if until is not None:
            if t_seconds < until:
                return INF
            del self.avoid[(u, v)]
        return world_cost(self.world, u, v, t_seconds)

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

    def path_cost_of(self, nodes):
        """Cost of a node path with the costs the planner holds now."""
        if not self.planner.legs:
            return 0.0
        graph = self.planner.legs[0].graph
        total = 0.0
        for a, b in zip(nodes, nodes[1:]):
            total += graph.get(a, {}).get(b, INF)
        return total

    def to_route(self, t_seconds, nodes=None):
        """R1's Route: nodes, planned ETA at each node, order id or None.

        nodes defaults to the planner's best path; pass a path to get the
        ETAs of another route through the same stops (hysteresis, Week 5).
        """
        from src.sim.interfaces import Route
        if nodes is None:
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


def __getattr__(name):
    """SimReplanner (Week 3) is now src.sim.agent_planner.AgentPlanner (Week 4).

    Imported lazily: agent_planner imports this module.
    """
    if name == "SimReplanner":
        from src.sim.agent_planner import AgentPlanner
        return AgentPlanner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
