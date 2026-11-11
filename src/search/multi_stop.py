"""Multi-stop routes with D* Lite: one planner per leg (R7, Week 3).

D* Lite plans to a single goal, so a vehicle with stops s1, s2, ..., sn keeps
one DStarLite per leg:

    leg 0: vehicle position -> s1     (start moves as the vehicle drives)
    leg 1: s1 -> s2                   (start fixed until the vehicle is at s1)
    ...

Every road change goes to every remaining leg, so each leg repairs itself
incrementally. When the vehicle reaches the goal of the current leg, that
planner is dropped and the next leg becomes current. The plan warns against
a single multi-goal D* Lite; this is the "one instance per leg" design.
"""

import math

from src.search.dstar_lite import INF, DStarLite


class MultiStopPlanner:
    def __init__(self, graph, start, stops, heuristic=None):
        """graph = {u: {v: cost}}; stops = the nodes to visit, in order."""
        self.heuristic = heuristic
        self.position = start
        self.stops = list(stops)
        self.legs = []
        leg_start = start
        for stop in self.stops:
            self.legs.append(DStarLite(graph, leg_start, stop, heuristic))
            leg_start = stop
        self._skip_reached()

    @classmethod
    def from_networkx(cls, G, start, stops, cost="free_flow_time",
                      heuristic=None):
        """Build from a NetworkX graph (same rules as DStarLite.from_networkx).

        The cheapest parallel road is kept and every node is included.
        """
        if callable(cost):
            cost_fn = cost
        else:
            def cost_fn(u, v, data):
                return data[cost]

        adj = {u: {} for u in G.nodes}
        for u, v, data in G.edges(data=True):
            c = float(cost_fn(u, v, data))
            adj[u][v] = min(c, adj[u].get(v, INF))
        return cls(adj, start, stops, heuristic)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    @property
    def done(self):
        """True when every stop has been reached."""
        return not self.legs

    @property
    def current_goal(self):
        return self.legs[0].goal if self.legs else None

    @property
    def remaining_stops(self):
        return [leg.goal for leg in self.legs]

    def _skip_reached(self):
        # Drop legs whose goal is where the vehicle already is (also repeated
        # stops at the same node).
        while self.legs and self.legs[0].goal == self.position:
            self.legs.pop(0)
            if self.legs:
                self.legs[0].move_start(self.position)

    # ------------------------------------------------------------------
    # Road changes: sent to every remaining leg
    # ------------------------------------------------------------------
    def update_edge_cost(self, u, v, new_cost):
        for leg in self.legs:
            leg.update_edge_cost(u, v, new_cost)

    def close_edge(self, u, v):
        for leg in self.legs:
            leg.close_edge(u, v)

    def reopen_edge(self, u, v, cost=None):
        for leg in self.legs:
            leg.reopen_edge(u, v, cost)

    def edge_cost(self, u, v):
        """Current cost the planner holds for road u -> v."""
        if self.legs:
            return self.legs[0].graph[u][v]
        raise ValueError("No legs left")

    # ------------------------------------------------------------------
    # Vehicle movement
    # ------------------------------------------------------------------
    def move_start(self, node):
        """The vehicle is now at node (one road further, or replanned)."""
        self.position = node
        if self.legs:
            self.legs[0].move_start(node)
        self._skip_reached()

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    def leg_paths(self):
        """One node list per remaining leg; [] for a leg that is unreachable."""
        return [leg.get_path() for leg in self.legs]

    def path(self):
        """Full node path through all remaining stops.

        Returns [] if any remaining stop cannot be reached in order (use
        unreachable_stops() to see which). If no stops remain, [position].
        """
        full = [self.position]
        for leg_path in self.leg_paths():
            if not leg_path:
                return []
            full.extend(leg_path[1:])
        return full

    def path_cost(self):
        """Total cost of path(); inf if a stop is unreachable."""
        total = 0.0
        for leg in self.legs:
            c = leg.path_cost()
            if c == INF:
                return INF
            total += c
        return total

    def unreachable_stops(self):
        """Stops whose leg has no route (closures can cause this)."""
        return [leg.goal for leg in self.legs if leg.path_cost() == INF]

    @property
    def expanded(self):
        """Nodes expanded by the last repair of every remaining leg."""
        return sum(leg.expanded for leg in self.legs)

    @property
    def total_expanded(self):
        return sum(leg.total_expanded for leg in self.legs)


def route_cost(graph, path):
    """Sum of graph[u][v] along a path (inf for an empty path)."""
    if not path:
        return math.inf
    return sum(graph[u][v] for u, v in zip(path, path[1:]))
