"""Yen's algorithm: the k cheapest loopless paths from source to target (for R5).

Idea in plain words:
1. The best path is just Dijkstra's answer.
2. To find the next path, take the last path found and try to leave it at each of its
   nodes in turn. The part before that node is the ROOT (kept as it is); the node where
   we leave is the SPUR node; the new part from there to the target is the SPUR PATH.
3. While searching for a spur path we block:
   - every road that another already-found path with the same root takes out of the
     spur node (otherwise we would just find that path again), and
   - every node of the root except the spur node (otherwise the path could loop back).
   Root + spur path is then a new loopless path: it is added to a list of candidates.
4. The cheapest candidate becomes the next path. Repeat until we have k paths or no
   candidates are left (then fewer than k paths exist).

Paths are lists of nodes. Parallel roads u -> v count as one road (the cheapest one).
"""
import heapq
import math

from src.search.dijkstra import dijkstra, free_flow_cost


def k_shortest_paths(G, source, target, k, cost_fn=None):
    """Up to k (path, cost) pairs, cheapest first, all loopless and different.

    cost_fn(u, v, data) gives an edge's cost (default: free-flow seconds); returning
    math.inf blocks the edge. Returns [] if the target cannot be reached or k < 1.
    """
    if cost_fn is None:
        cost_fn = free_flow_cost

    def path_cost(path):
        """Sum of edge costs, taking the cheapest parallel road for each step."""
        total = 0.0
        for u, v in zip(path, path[1:]):
            datas = G[u][v].values() if G.is_multigraph() else [G[u][v]]
            total += min(cost_fn(u, v, data) for data in datas)
        return total

    first = dijkstra(G, source, target, cost_fn)
    if k < 1 or not first.path:
        return []
    found = [(first.path, path_cost(first.path))]
    seen = {tuple(first.path)}                # paths already found or waiting as candidates
    candidates = []                           # heap of (cost, insertion order, path)
    order = 0

    while len(found) < k:
        last_path = found[-1][0]
        for i in range(len(last_path) - 1):   # leave the last path at each node except target
            spur = last_path[i]
            root = last_path[:i + 1]          # source ... spur

            # Roads out of the spur node already used by found paths with this same root.
            blocked_edges = {(p[i], p[i + 1]) for p, _ in found if p[:i + 1] == root}
            blocked_nodes = set(root[:-1])    # root nodes before the spur: no loops

            def spur_cost(u, v, data):
                if (u, v) in blocked_edges or u in blocked_nodes or v in blocked_nodes:
                    return math.inf
                return cost_fn(u, v, data)

            spur_result = dijkstra(G, spur, target, spur_cost)
            if not spur_result.path:          # no way to the target from here
                continue
            path = root[:-1] + spur_result.path
            if tuple(path) not in seen:
                seen.add(tuple(path))
                heapq.heappush(candidates, (path_cost(path), order, path))
                order += 1

        if not candidates:                    # fewer than k paths exist
            break
        cost, _, path = heapq.heappop(candidates)
        found.append((path, cost))

    return found
