# Search module (R2)

## Files
- `heuristics.py`: `make_heuristic(G)` returns `h(node, goal)`, a lower bound on travel time.
- `dijkstra.py`: Dijkstra from scratch with `heapq`, plus the shared `SearchResult` (path, cost, expanded).
- `astar.py`: A* from scratch, the same as Dijkstra but ordered by `f = g + h`.
- `../world/graph_loader.py`: `load_road_graph(name)` prepares a graph for search.
- `../viz/plot_route.py`: draws one A* route to `docs/route_example.png`.

## Cost model
- Edge cost = `free_flow_time` = `length / (speed_kmh / 3.6)` seconds.
- Speeds come from the OSM `maxspeed` tag. If it is missing (`speed_imputed = True`), we use the median
  tagged speed for that road class in the same graph (if at least 5 edges are tagged), otherwise a default
  (motorway 80, trunk 60, primary 50, secondary 40, tertiary 35, unclassified 30, residential 25,
  living_street 15, other 25). `_link` roads count as their main class.
- Where parallel edges join the same (u, v), only the fastest is kept.

## Heuristic: admissible and consistent
`h(n, goal) = haversine(n, goal) / max_speed`, where `max_speed` is the fastest edge speed (60 km/h here).
- Admissible: no road is shorter than the great-circle line (OSMnx measured lengths with the same
  haversine formula), and no road is faster than `max_speed`, so `h` never overestimates.
- Consistent: `h(u) <= cost(u, v) + h(v)` by the triangle inequality, so a node's cost is final when it is popped.
- We use lat/lon, not projected x/y: UTM distances here are up to 0.19% longer than haversine distances.
  The saved graphs only hold x/y, so `load_road_graph` converts them back to lat/lon in memory.
- This holds only if every edge cost is at least `free_flow_time` (for example, extra delay from congestion is fine).

## Blocked edges
Pass `cost_fn(u, v, data)`. If it returns `math.inf`, the edge is blocked and never used.
If no route exists, the result is `path == []` and `cost == math.inf`.

## Tests
From the repo root: `python -m pytest` (add `-s` to see the expansion counts).
Tests cover a hand-checked 5-node graph, a networkx cross-check (200 small and 1,000 full-graph pairs),
route continuity, blocked edges, admissibility/consistency, and A* expanding no more nodes than Dijkstra.
