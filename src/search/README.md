# Search module (R2)

## Files
- `heuristics.py`: `make_heuristic(G)` returns `h(node, goal)`, a lower bound on travel time.
- `dijkstra.py`: Dijkstra from scratch with `heapq`, plus the shared `SearchResult` (path, cost, expanded).
- `astar.py`: A* from scratch, the same as Dijkstra but ordered by `f = g + h`.
- `dstar_lite.py` (R7): `DStarLite` incremental search (Koenig & Likhachev 2002). See the D* Lite section below.
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

## D* Lite (R7), baseline version
`src/search/dstar_lite.py` replans after road changes without starting over. This is the **baseline
version**: its heuristic is 0, so it is not guided toward the vehicle and explores like an incremental
backward Dijkstra. One planner covers one leg (start to one goal); a vehicle with several stops needs one
planner per leg.

```python
d = DStarLite.from_networkx(G, start, goal)          # or DStarLite({u: {v: cost}}, start, goal)
d.get_path()                     # node list, [] if unreachable; d.path_cost() gives its cost
d.update_edge_cost(u, v, c)      # new cost; math.inf closes the road
d.close_edge(u, v)               # impassable until reopened
d.reopen_edge(u, v)              # back to the cost before closing (or reopen_edge(u, v, c))
d.move_start(node)               # the vehicle moved; call get_path() again
d.expanded, d.total_expanded     # nodes expanded in the last repair / since construction
```
- `from_networkx(G, start, goal, cost="free_flow_time")`: `cost` is an edge attribute or a function
  `cost(u, v, data)` like `astar`'s `cost_fn`. Every node is included (also dead ends); the cheapest
  parallel road is kept.
- Costs must be >= 0. Zero-cost roads are fine. Changes are repaired lazily, on the next `get_path()`.
- Returns a plain node list, not a `SearchResult` (to be aligned with the Route/Planner interface).

### Timing on the Secunderabad graph (2,377 nodes, 6,056 edges)
30 random trips (seed 42, at least 6 roads long), medians, `time.perf_counter()`, measured in a cloud Linux container.
Rough figures: they will differ on other machines.

| Step | D* Lite | A* (R2, haversine heuristic) |
| --- | --- | --- |
| First plan | 5.3 ms (+ 4.3 ms `from_networkx`), 1,420 nodes expanded | 4.6 ms, 329 nodes expanded |
| Replan after one road on the route gets 5x slower | 1.6 ms, 393 nodes expanded | 5.5 ms (from scratch) |
| Replan after closing the vehicle's next road | 0.8 ms, 154 nodes expanded | 5.6 ms (from scratch), 401 nodes expanded |

- The first plan is slower than A* because the zero heuristic expands about 4x more nodes.
- Replans are 3-7x faster than rerunning A*, because only nodes whose values changed are reprocessed.
- Before the predecessor map (PR #5 review) the same trips took 179 ms for the first plan and 46 ms per replan:
  every update scanned all 2,377 nodes to find the roads into a node.
- Next step (Week 3): R2's haversine heuristic with `km`, and the full benchmark against the number of changed edges.
