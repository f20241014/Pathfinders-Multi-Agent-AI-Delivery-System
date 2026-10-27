
"""D* Lite pathfinding for weighted directed graphs."""

import heapq
import math

INF = math.inf


class DStarLite:
    def __init__(self, graph, start, goal):
        self.graph = {u: dict(edges) for u, edges in graph.items()}
        self.start = start
        self.last_start = start
        self.goal = goal
        self.km = 0

        if start not in self.graph or goal not in self.graph:
            raise KeyError("Start and goal must exist in graph")

        self.g = {u: INF for u in self.graph}
        self.rhs = {u: INF for u in self.graph}
        self.rhs[goal] = 0

        self.queue = []
        self.counter = 0
        self._push(goal)

    def heuristic(self, a, b):
        # Zero heuristic works for arbitrary nonnegative edge costs.
        return 0

    def key(self, u):
        m = min(self.g[u], self.rhs[u])
        return (
            m + self.heuristic(self.start, u) + self.km,
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

            elif self.g[u] > self.rhs[u]:
                self.g[u] = self.rhs[u]

                for pred in self.graph:
                    if u in self.graph[pred]:
                        self._update_vertex(pred)

            else:
                self.g[u] = INF
                self._update_vertex(u)

                for pred in self.graph:
                    if u in self.graph[pred]:
                        self._update_vertex(pred)

    def move_start(self, new_start):
        if new_start not in self.graph:
            raise KeyError(f"Unknown node: {new_start}")

        self.km += self.heuristic(self.last_start, new_start)
        self.last_start = new_start
        self.start = new_start

    def update_edge_cost(self, u, v, new_cost):
        """Update the cost of an existing directed road."""
        if u not in self.graph or v not in self.graph[u]:
            raise KeyError(f"Unknown directed edge: {u} -> {v}")

        if not math.isfinite(new_cost) or new_cost < 0:
            raise ValueError("Edge cost must be finite and nonnegative")

        self.graph[u][v] = float(new_cost)
        self._update_vertex(u)

    def get_path(self):
        self.compute_shortest_path()

        if self.g[self.start] == INF:
            return []

        path = [self.start]
        current = self.start
        visited = {current}

        while current != self.goal:
            choices = [
                (cost + self.g[v], v)
                for v, cost in self.graph[current].items()
            ]

            if not choices:
                return []

            best_cost, next_node = min(choices)

            if best_cost == INF or next_node in visited:
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
