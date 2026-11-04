"""Time-dependent Dijkstra and A*: an edge's cost depends on when the vehicle enters it.

The cost of edge (u, v) is edge_time_fn(u, v, t), evaluated at the time the vehicle
ENTERS the edge:  t = depart_t + g,  where g = seconds travelled so far.
This is the same rule as the simulator ("traversal time is fixed at edge entry").

Pass world.edge_time as edge_time_fn. Times are absolute seconds from midnight.

FIFO assumption: entering an edge later never means leaving it earlier, i.e.
t1 < t2  implies  t1 + T(t1) <= t2 + T(t2).  Under FIFO, arriving at a node as early
as possible is always best, so (like plain Dijkstra) a node's arrival time is final when
it is popped, and the answer is the earliest possible arrival. Without FIFO, waiting
or arriving later at some node could sometimes help; these searches do not consider
waiting. See src/search/fifo_check.py.
"""
import heapq
import math
from dataclasses import dataclass

from src.search.dijkstra import SearchResult, build_path
from src.search.heuristics import make_heuristic


@dataclass
class TDSearchResult(SearchResult):
    arrival_t: float  # depart_t + cost (math.inf if unreachable)


def _search(G, source, target, depart_t, edge_time_fn, heuristic):
    """Shared loop. heuristic(node, goal) = 0 everywhere gives Dijkstra."""
    best = {source: 0.0}                      # g: seconds travelled to reach each node
    parent = {}                               # parent[v] = node we came from to reach v
    finalised = set()                         # nodes whose arrival time can no longer improve
    heap = [(heuristic(source, target), source)]  # queue of (f = g + h, node)
    expanded = 0

    while heap:
        _, u = heapq.heappop(heap)            # node with the smallest f
        if u in finalised:                    # an older, more expensive copy: skip it
            continue
        finalised.add(u)
        expanded += 1
        g = best[u]
        if u == target:                       # reached the goal: stop early
            path = build_path(parent, source, target)
            return TDSearchResult(path, g, expanded, depart_t + g)

        for v in G.successors(u):             # each neighbour once (parallel roads: the
            if v in finalised:                # edge_time_fn picks the road itself)
                continue
            cost = edge_time_fn(u, v, depart_t + g)   # cost at the time we ENTER (u, v)
            if cost == math.inf:              # closed road at that time: never use it
                continue
            new_g = g + cost
            if new_g < best.get(v, math.inf):
                best[v] = new_g
                parent[v] = u
                heapq.heappush(heap, (new_g + heuristic(v, target), v))

    return TDSearchResult([], math.inf, expanded, math.inf)   # target unreachable


def dijkstra_td(G, source, target, depart_t, edge_time_fn, heuristic=None):
    """Time-dependent Dijkstra. `heuristic` is ignored (kept so both have one signature)."""
    return _search(G, source, target, depart_t, edge_time_fn, lambda node, goal: 0.0)


def astar_td(G, source, target, depart_t, edge_time_fn, heuristic=None):
    """Time-dependent A*.

    heuristic(node, goal) must never overestimate the remaining time. The default,
    make_heuristic(G) (haversine / max speed), is valid as long as every edge_time is at
    least its free-flow time (traffic multipliers are >= 1 and closures are inf).
    """
    if heuristic is None:
        heuristic = make_heuristic(G)
    return _search(G, source, target, depart_t, edge_time_fn, heuristic)
