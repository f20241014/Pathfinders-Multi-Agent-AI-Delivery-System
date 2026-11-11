"""Travel-time matrix between many nodes, built on a from-scratch Dijkstra (heapq).

Snapshot convention (same as R4's WorldTravel): every edge is costed at ONE time t,
the moment the matrix is asked for. Costs do not change while the vehicle drives
(no time-dependent search here; use time_dependent.py for that). If the world changes
(a new closure, a forecast refresh), call clear_cache(): cached rows are not updated.

Cost convention (same as dijkstra.py): cost_fn(u, v, data) returns an edge's cost in
seconds; math.inf means the edge is blocked and is never used. cost_fn_factory(t)
must return such a cost_fn for time t.

Which cost function to pass (D10): for planning, pass a cost function built from
PREDICTED times plus the live closure/spike feed (as R4's WorldTravel does), not
World.cost_fn_at. cost_fn_at uses actual edge_time, which is ground truth for the
simulator and metrics only. Planning with it would give agents knowledge of the future
and break D10 (all conditions see the same information). See docs/travel_matrix.md.
"""
import heapq
import math


def _dijkstra_costs(G, source, cost_fn, targets=None):
    """Shared loop. Returns (settled costs, nodes expanded, whole reachable set settled?)."""
    if source not in G:
        raise KeyError(f"Node {source} not in graph.")
    remaining = None if targets is None else set(targets)  # targets not yet settled
    best = {source: 0.0}                      # cheapest known cost to reach each node
    settled = {}                              # node -> final cost
    heap = [(0.0, source)]                    # priority queue of (cost so far, node)
    expanded = 0

    while heap:
        g, u = heapq.heappop(heap)
        if u in settled:                      # an older, more expensive copy: skip it
            continue
        settled[u] = g                        # u's cost is now final
        expanded += 1
        if remaining is not None:
            remaining.discard(u)
            if not remaining:                 # every target settled: stop early
                return settled, expanded, False

        for _, v, data in G.out_edges(u, data=True):   # every road leaving u
            if v in settled:
                continue
            cost = cost_fn(u, v, data)
            if cost == math.inf:              # blocked road: never use it
                continue
            new_g = g + cost
            if new_g < best.get(v, math.inf):
                best[v] = new_g
                heapq.heappush(heap, (new_g, v))

    return settled, expanded, True            # queue empty: everything reachable is settled


def single_source_costs(G, source, cost_fn, targets=None):
    """Cheapest cost (seconds) from source to every node, or only to `targets`.

    With targets=None, runs Dijkstra to the end and returns a value for every node of G.
    With targets given, stops as soon as all of them are settled and returns the settled
    nodes plus every target (math.inf for a target that cannot be reached).
    """
    settled, _, _ = _dijkstra_costs(G, source, cost_fn, targets)
    wanted = G.nodes if targets is None else targets
    return {**{n: math.inf for n in wanted}, **settled}


class TravelTimeMatrix:
    """N x N travel times at a frozen time t, with one cached Dijkstra row per (t, source).

    cost_fn_factory(t) must return cost_fn(u, v, data) for time t. For planning, build it
    from predicted times, not world.cost_fn_at (see the module docstring, D10).
    Counters: hits / misses count rows (one per source and call); expanded is the total
    number of nodes popped by all Dijkstra runs so far.
    """

    def __init__(self, G, cost_fn_factory):
        self.G = G
        self.cost_fn_factory = cost_fn_factory
        self._rows = {}       # (t, source) -> (settled costs, exhausted)
        self.hits = 0
        self.misses = 0
        self.expanded = 0

    def clear_cache(self):
        """Forget all rows (call after the world changes). Counters are kept."""
        self._rows.clear()

    def _row_has(self, row, targets):
        settled, exhausted = row
        return exhausted or all(n in settled for n in targets)

    def row(self, source, t, targets):
        """Costs from source at time t, covering every node in `targets`."""
        key = (float(t), source)
        row = self._rows.get(key)
        if row is not None and self._row_has(row, targets):
            self.hits += 1
        else:
            self.misses += 1
            settled, expanded, exhausted = _dijkstra_costs(
                self.G, source, self.cost_fn_factory(t), targets)
            self.expanded += expanded
            row = (settled, exhausted)
            self._rows[key] = row
        settled, _ = row
        return {n: settled.get(n, math.inf) for n in targets}

    def travel_time_matrix(self, nodes, t):
        """matrix[i][j] = seconds from nodes[i] to nodes[j] at time t.

        Directed, so matrix[i][j] and matrix[j][i] can differ. Diagonal is 0;
        math.inf where no route exists (for example, all ways blocked).
        """
        nodes = list(nodes)
        targets = set(nodes)
        matrix = []
        for s in nodes:
            costs = self.row(s, t, targets)
            matrix.append([costs[d] for d in nodes])
        return matrix
