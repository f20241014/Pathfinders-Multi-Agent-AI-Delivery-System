"""A* shortest path, written from scratch with a heap (no networkx search).

Same as Dijkstra, except the queue is ordered by f = g + h:
g = cost already travelled, h = optimistic guess of the cost still to go.
"""
import heapq
import math

from src.search.dijkstra import SearchResult, build_path, free_flow_cost
from src.search.heuristics import make_heuristic


def astar(G, source, target, cost_fn=None, heuristic=None):
    """Cheapest path from source to target using A*.

    cost_fn(u, v, data) gives an edge's cost; returning math.inf blocks the edge.
    heuristic(node, goal) must never overestimate the remaining cost.
    """
    if cost_fn is None:
        cost_fn = free_flow_cost              # default: free-flow travel time
    if heuristic is None:
        heuristic = make_heuristic(G)         # straight-line distance / max speed

    best = {source: 0.0}                      # cheapest known cost (g) to reach each node
    parent = {}                               # parent[v] = node we came from to reach v
    finalised = set()                         # nodes whose cost can no longer improve
    heap = [(heuristic(source, target), source)]  # queue of (f = g + h, node)
    expanded = 0

    while heap:
        _, u = heapq.heappop(heap)            # node with the smallest f
        if u in finalised:                    # an older, more expensive copy: skip it
            continue
        finalised.add(u)                      # with a consistent h, u's cost is now final
        expanded += 1
        g = best[u]                           # real cost to reach u
        if u == target:                       # reached the goal: stop early
            return SearchResult(build_path(parent, source, target), g, expanded)

        for _, v, data in G.out_edges(u, data=True):   # every road leaving u
            if v in finalised:
                continue
            cost = cost_fn(u, v, data)
            if cost == math.inf:              # blocked road: never use it
                continue
            new_g = g + cost                  # cost to reach v through u
            if new_g < best.get(v, math.inf): # cheaper than anything found before?
                best[v] = new_g
                parent[v] = u
                f = new_g + heuristic(v, target)   # add the guess of what is left
                heapq.heappush(heap, (f, v))

    return SearchResult([], math.inf, expanded)    # queue empty: target unreachable
