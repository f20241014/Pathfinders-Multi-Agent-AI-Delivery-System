"""Dijkstra's shortest path, written from scratch with a heap (no networkx search)."""
import heapq
import math
from dataclasses import dataclass


@dataclass
class SearchResult:
    path: list        # nodes from source to target ([] if unreachable)
    cost: float       # total cost of the path (math.inf if unreachable)
    expanded: int     # how many nodes were popped and finalised


def free_flow_cost(u, v, data):
    """Default edge cost: free-flow travel time in seconds."""
    return data["free_flow_time"]


def build_path(parent, source, target):
    """Walk the parent links backwards from target to source, then reverse."""
    path = [target]
    while path[-1] != source:
        path.append(parent[path[-1]])
    path.reverse()
    return path


def dijkstra(G, source, target, cost_fn=None):
    """Cheapest path from source to target.

    cost_fn(u, v, data) gives an edge's cost; returning math.inf blocks the edge.
    """
    if cost_fn is None:
        cost_fn = free_flow_cost              # default: free-flow travel time

    best = {source: 0.0}                      # cheapest known cost to reach each node
    parent = {}                               # parent[v] = node we came from to reach v
    finalised = set()                         # nodes whose cost can no longer improve
    heap = [(0.0, source)]                    # priority queue of (cost so far, node)
    expanded = 0

    while heap:
        g, u = heapq.heappop(heap)            # take the cheapest node waiting in the queue
        if u in finalised:                    # an older, more expensive copy: skip it
            continue
        finalised.add(u)                      # u's cost is now final
        expanded += 1
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
                heapq.heappush(heap, (new_g, v))  # old entries for v stay but are skipped later

    return SearchResult([], math.inf, expanded)    # queue empty: target unreachable
