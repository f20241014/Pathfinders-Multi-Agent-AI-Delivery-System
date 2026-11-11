"""D* Lite pathfinding for weighted directed graphs.

The heuristic is optional. With the default (zero) the search is not guided
and behaves like an incremental backward Dijkstra: the baseline version. Pass
heuristic=h, where h(a, b) is a lower bound on the cost of driving from a to
b (for example make_heuristic(G) from heuristics.py); km then grows as the
vehicle moves. A closed road has cost math.inf. Timings: src/search/README.md.
"""

import heapq
import math

INF = math.inf
H_SLACK = 1e-9   # relative slack on a given heuristic, see heuristic()


class DStarLite:
    def __init__(self, graph, start, goal, heuristic=None):
        # Every node becomes a key, including dead ends that only appear as
        # a neighbour (no roads out).
        self.graph = {u: dict(edges) for u, edges in graph.items()}
        for edges in graph.values():
            for v in edges:
                self.graph.setdefault(v, {})

        self.start = start
        self.last_start = start
        self.goal = goal
        self.km = 0
        self._h = heuristic
        self._h_start = {}       # cache: u -> heuristic(start, u)

        if start not in self.graph or goal not in self.graph:
            raise KeyError("Start and goal must exist in graph")

        # Reverse adjacency, built once: pred[v] = nodes with a road into v.
        # Roads are never added or removed (a closure is cost inf), so it
        # stays valid.
        self.pred = {u: set() for u in self.graph}
        for u, edges in self.graph.items():
            for v in edges:
                self.pred[v].add(u)

        self.closed = {}          # (u, v) -> cost before close_edge
        self.expanded = 0         # nodes expanded in the last repair
        self.total_expanded = 0   # nodes expanded since construction

        self.g = {u: INF for u in self.graph}
        self.rhs = {u: INF for u in self.graph}
        self.rhs[goal] = 0

        self.queue = []
        self.counter = 0
        self._push(goal)

    @classmethod
    def from_networkx(cls, G, start, goal, cost="free_flow_time",
                      heuristic=None):
        """Build a planner from a NetworkX (Multi)DiGraph.

        cost is an edge attribute name, or a function cost(u, v, data) like
        astar's cost_fn. Every node is included, also nodes with no roads
        out. Where parallel roads join the same (u, v), the cheapest is kept.
        heuristic is passed on unchanged (see the module docstring).
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
        return cls(adj, start, goal, heuristic)

    def heuristic(self, a, b):
        """Lower bound on the cost from a to b.

        Zero unless a heuristic was given; zero works for any nonnegative
        costs. A given heuristic must never overestimate and must obey the
        triangle inequality h(a, c) <= h(a, b) + h(b, c).

        A given heuristic is shrunk by H_SLACK: one that is exact on straight
        roads (like R2's) can overestimate by float rounding (~1e-12 s),
        which can stop the repair loop one node early. The shrunk value is
        still a lower bound and still obeys the triangle inequality.
        """
        if self._h is None:
            return 0
        return self._h(a, b) * (1 - H_SLACK)

    def _h_from_start(self, u):
        # Keys need h(start, u) again and again; start only changes in
        # move_start, which clears this cache.
        h = self._h_start.get(u)
        if h is None:
            h = self._h_start[u] = self.heuristic(self.start, u)
        return h

    def key(self, u):
        m = min(self.g[u], self.rhs[u])
        return (
            m + self._h_from_start(u) + self.km,
            m,
        )

    def _push(self, u):
        self.counter += 1
        k1, k2 = self.key(u)
        heapq.heappush(
            self.queue, (k1, k2, self.counter, u)
        )

    def _top_key(self):
        while self.queue:
            k1, k2, _, u = self.queue[0]
            if self.g[u] == self.rhs[u]:
                heapq.heappop(self.queue)
            else:
                return (k1, k2)
        return (INF, INF)

    def _update_vertex(self, u):
        if u != self.goal:
            self.rhs[u] = min(
                (
                    cost + self.g[v]
                    for v, cost in self.graph[u].items()
                ),
                default=INF,
            )

        if self.g[u] != self.rhs[u]:
            self._push(u)

    def compute_shortest_path(self):
        self.expanded = 0
        while (
            self._top_key() < self.key(self.start)
            or self.rhs[self.start] != self.g[self.start]
        ):
            if not self.queue:
                break

            k1, k2, _, u = heapq.heappop(self.queue)
            old_key = (k1, k2)
            new_key = self.key(u)

            if old_key < new_key:
                self._push(u)
                continue

            self.expanded += 1
            if self.g[u] > self.rhs[u]:
                self.g[u] = self.rhs[u]

                for pred in self.pred[u]:
                    self._update_vertex(pred)

            else:
                self.g[u] = INF
                self._update_vertex(u)

                for pred in self.pred[u]:
                    self._update_vertex(pred)

        self.total_expanded += self.expanded

    def move_start(self, new_start):
        if new_start not in self.graph:
            raise KeyError(f"Unknown node: {new_start}")

        self.km += self.heuristic(self.last_start, new_start)
        self.last_start = new_start
        self.start = new_start
        self._h_start.clear()

    def update_edge_cost(self, u, v, new_cost):
        """Update the cost of an existing directed road.

        new_cost = math.inf closes the road (impassable).
        """
        if u not in self.graph or v not in self.graph[u]:
            raise KeyError(f"Unknown directed edge: {u} -> {v}")

        if math.isnan(new_cost) or new_cost < 0:
            raise ValueError("Edge cost must be nonnegative (or inf)")

        self.graph[u][v] = float(new_cost)
        self._update_vertex(u)

    def close_edge(self, u, v):
        """Close a road: it becomes impassable until reopened."""
        if u not in self.graph or v not in self.graph[u]:
            raise KeyError(f"Unknown directed edge: {u} -> {v}")

        if (u, v) not in self.closed:
            self.closed[(u, v)] = self.graph[u][v]
        self.update_edge_cost(u, v, INF)

    def reopen_edge(self, u, v, cost=None):
        """Reopen a road, at its cost before closing unless cost is given."""
        if cost is None:
            if (u, v) not in self.closed:
                raise KeyError(f"Edge {u} -> {v} is not closed; give a cost")
            cost = self.closed[(u, v)]

        if not math.isfinite(cost):
            raise ValueError("A reopened road needs a finite cost")

        self.update_edge_cost(u, v, cost)
        self.closed.pop((u, v), None)

    def get_path(self):
        self.compute_shortest_path()

        if self.g[self.start] == INF:
            return []

        path = [self.start]
        current = self.start
        visited = {current}

        while current != self.goal:
            # Never step back to a visited node; on equal cost prefer the
            # neighbour closer to the goal (matters for zero-cost roads).
            choices = [
                (cost + self.g[v], self.g[v], v)
                for v, cost in self.graph[current].items()
                if v not in visited
            ]

            if not choices:
                return []

            best_cost, _, next_node = min(
                choices, key=lambda c: (c[0], c[1])
            )

            if best_cost == INF:
                return []

            path.append(next_node)
            visited.add(next_node)
            current = next_node

        return path

    def path_cost(self, path=None):
        if path is None:
            path = self.get_path()

        if not path:
            return INF

        return sum(
            self.graph[u][v]
            for u, v in zip(path, path[1:])
        )
