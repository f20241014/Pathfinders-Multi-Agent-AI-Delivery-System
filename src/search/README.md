# Search module (R2)

## Files
- `heuristics.py`: `make_heuristic(G)` returns `h(node, goal)`, a lower bound on travel time.
- `dijkstra.py`: Dijkstra from scratch with `heapq`, plus the shared `SearchResult` (path, cost, expanded).
- `astar.py`: A* from scratch, the same as Dijkstra but ordered by `f = g + h`.
- `dstar_lite.py` (R7): `DStarLite` incremental search (Koenig & Likhachev 2002). See the D* Lite section below.
- `multi_stop.py` (R7): `MultiStopPlanner`, one D* Lite per leg for a vehicle with several stops.
- `sim_replanner.py` (R7): D* Lite inside R1's simulator (`SimReplanner`, `reroute`).
- `benchmark_replan.py` (R7): D* Lite vs A* replanning benchmark, figure F3.
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

## D* Lite (R7)
`src/search/dstar_lite.py` replans after road changes without starting over. With the default zero
heuristic it is the **baseline version** (not guided; explores like an incremental backward Dijkstra).
Pass `heuristic=make_heuristic(G)` to guide it with R2's haversine bound; `km` then grows as the vehicle
moves. One planner covers one leg (start to one goal); a vehicle with several stops needs one planner per leg.

```python
d = DStarLite.from_networkx(G, start, goal)          # or DStarLite({u: {v: cost}}, start, goal)
d = DStarLite.from_networkx(G, start, goal, heuristic=make_heuristic(G))   # guided
d.get_path()                     # node list, [] if unreachable; d.path_cost() gives its cost
d.update_edge_cost(u, v, c)      # new cost; math.inf closes the road
d.close_edge(u, v)               # impassable until reopened
d.reopen_edge(u, v)              # back to the cost before closing (or reopen_edge(u, v, c))
d.move_start(node)               # the vehicle moved; call get_path() again
d.expanded, d.total_expanded     # nodes expanded in the last repair / since construction
```
- `from_networkx(G, start, goal, cost="free_flow_time", heuristic=None)`: `cost` is an edge attribute or a
  function `cost(u, v, data)` like `astar`'s `cost_fn`. Every node is included (also dead ends); the
  cheapest parallel road is kept.
- Costs must be >= 0. Zero-cost roads are fine. Changes are repaired lazily, on the next `get_path()`.
- A heuristic must never overestimate, so with `make_heuristic(G)` costs must stay >= `free_flow_time`
  (traffic only slows roads; closures are `inf`). D* Lite shrinks a given heuristic by `H_SLACK = 1e-9`:
  R2's bound is exact on straight roads, and float rounding (~1e-12 s) could otherwise stop the repair one
  node early and lose the route (found on the full map; regression test in `tests/test_dstar_lite.py`).
- Returns a plain node list, not a `SearchResult` (to be aligned with the Route/Planner interface).

### Timing on the Secunderabad graph (2,377 nodes, 6,056 edges)
30 random trips (seed 42, at least 6 roads long), medians, `time.perf_counter()`, measured in a cloud Linux
container. Rough figures: they will differ on other machines. Replans: (1) one road in the middle of the
route becomes 5x slower; (2) then the vehicle's next road closes.

| Step | D* Lite, h = 0 | D* Lite, haversine h | A* from scratch (R2) |
| --- | --- | --- | --- |
| First plan | 5.3 ms, 1,420 expanded | 5.2 ms, 471 expanded | 4.6 ms, 329 expanded |
| Replan after a slower road | 1.6 ms, 393 expanded | 1.6 ms, 218 expanded | 5.5 ms |
| Replan after a closure | 0.8 ms, 154 expanded | 1.5 ms, 141 expanded | 5.6 ms, 401 expanded |

`from_networkx` adds about 4.5 ms once per planner.
- Replans are 3-7x faster than rerunning A*, because only nodes whose values changed are reprocessed.
- The heuristic cuts expansions about 3x on the first plan, but each haversine call costs time, so the
  run time is about the same. `h(start, u)` is cached until the vehicle moves.
- Before the predecessor map (PR #5 review) the same trips took 179 ms for the first plan and 46 ms per
  replan: every update scanned all 2,377 nodes to find the roads into a node.
- Week 3 benchmark against the number of changed roads: see F3 below.

### Tests
`tests/test_multi_stop.py`, `tests/test_sim_replanner.py` (inside R1's sim, vs A*) and
`tests/test_benchmark_replan.py` cover Week 3. `tests/test_dstar_lite.py` checks every D* Lite cost against `astar.py`: hand-checked toy graph, grids,
closures and reopening, moving start (km), dead ends, zero-cost roads, 500 random change sequences, 500
changes in one run (grid and real map, with and without heuristic), and the full-map rounding regression.

## Week 2 (R2)

All times are absolute seconds from midnight; the sim window is 06:00-10:00 (21600-36000 s).
Every script uses a fixed seed and is run from the repo root.

### Time-dependent search and the FIFO limitation
`time_dependent.py`: `dijkstra_td` and `astar_td(G, source, target, depart_t, edge_time_fn, heuristic=None)`.
Pass `world.edge_time` as `edge_time_fn`. An edge is costed at the time the vehicle **enters** it,
`t = depart_t + g` (the sim's "traversal time fixed at edge entry" rule), so a route's time is exactly what the
sim will produce if nothing changes on the way. `inf` = closed at that time, never used. The result is a
`TDSearchResult`: `path`, `cost` (seconds), `expanded`, `arrival_t`.
- Both are guaranteed fastest only under **FIFO** (entering an edge later never means leaving it earlier).
  `fifo_check.py` found that FIFO does not hold exactly with R6's traffic model: multipliers change in 5-minute
  steps, and a drop at a step boundary lets a later car leave first. On 500 sampled edges, 14.8% violate on a 5 s
  grid and 60.6% on a 1 s grid, at fewer than 0.1% of the grid times; worst case 61.7 s. The searches do not
  consider waiting, so near step boundaries a waiting route could be faster. Documented limitation; details in
  `docs/fifo_check.md`.
- On 200 real pairs x 3 departure times, `astar_td` and `dijkstra_td` gave the same cost on every pair.

### Yen's k alternative paths (for R5)
`yen.py`: `k_shortest_paths(G, source, target, k, cost_fn=None)` returns up to k `(path, cost)` pairs,
cheapest first, loopless and distinct (fewer if fewer exist, `[]` if unreachable). Built on our `dijkstra`:
for each node of the last path found, keep the path up to it (root) and search a new way on (spur path) with
the root's nodes and the already-used next roads blocked. Costs match `networkx.shortest_simple_paths` on the
toy graph and 50 real pairs for k = 1, 3, 5. Works with `cost_fn=world.cost_fn_at(t)` (traffic, closures).

### Dijkstra vs A* benchmark (F2)
200 random OD pairs, free-flow costs, same cost on every pair (`docs/benchmark_dijkstra_astar.md`,
per-pair CSV next to it, figure `reports/figures/F2_astar_vs_dijkstra.png`). Dijkstra / A*:

| | Ratio of means | Median of the per-pair ratio |
| --- | --- | --- |
| Nodes expanded | 2.27 | 2.35 |
| Run time | 0.94 | 0.96 |

A* never expanded more nodes than Dijkstra, but it was not faster. Run times are wall-clock
(`time.perf_counter()`), single runs on one Windows laptop with Python 3.14.5; they differ on other machines.

### Heuristic checks
`heuristic_check.py` (`docs/heuristic_checks.md`), traffic model active:
- free-flow, 300 targets, true cost-to-go from our own reverse Dijkstra: 0 admissibility violations in 712,800
  (node, target) pairs and 0 consistency violations in 1,816,800 (edge, target) pairs (tolerance 1e-6 s);
  18 + 18 values were below zero by at most 7.5e-11 s, counted and reported in the doc;
- with traffic: smallest `edge_time / free_flow_time` = 1.0 (traffic never makes a road faster than free-flow);
  on 200 `dijkstra_td` trips x 3 departures, `h` never exceeded the remaining time on the route (7 values below
  zero by at most 1.5e-11 s).

### Where A*'s time goes
`heuristic_cost.py` (section at the end of `docs/benchmark_dijkstra_astar.md`), same 200 pairs: A* calls the
heuristic 628 times per trip on average; one call takes 3.0 us against 0.077 us for an edge-cost lookup. Mean run
time: Dijkstra 3.98 ms, A* 4.32 ms, A* with the heuristic precomputed for the target 1.90 ms. Machine-specific.

### How to run each script
```
python -m pytest --ignore=tests/test_prediction.py -q
python -m src.search.fifo_check --edges 500 --steps 5 1 --seed 0 --prediction "..."
python -m src.search.benchmark --pairs 200 --seed 42 --prediction "..."
python -m src.search.benchmark --from-csv          # rebuild the doc from the CSV, no re-timing
python -m src.search.heuristic_check --targets 300 --pairs 200 --seed 0 --prediction "..."
python -m src.search.heuristic_cost --pairs 200 --seed 42 --calls 100000
```
Tests: `tests/test_search_time_dependent.py`, `test_fifo_check.py`, `test_search_yen.py`, `test_benchmark.py`,
`test_heuristic_check.py`, `test_heuristic_cost.py`.

## Travel-time matrix (Week 3)
`travel_matrix.py`: N x N travel times at a frozen time t (snapshot), one cached Dijkstra row per (t, source).
```python
tm = TravelTimeMatrix(world.G, cost_fn_factory)    # cost_fn_factory(t) -> cost_fn(u, v, data)
m = tm.travel_time_matrix(nodes, t=28800)          # m[i][j] seconds, directed, inf = no route
```
Repeat calls are cache hits (`tm.hits`, `tm.misses`, `tm.expanded`); `clear_cache()` after the world changes. See `docs/travel_matrix.md`.

**Warning (D10):** for planning, pass a cost function built from PREDICTED times plus the live closure/spike feed
(as R4's WorldTravel does), not `World.cost_fn_at`. `cost_fn_at` uses actual `edge_time`, which is ground truth for
the simulator and metrics only. Planning with it would give agents knowledge of the future and break D10 (all
conditions see the same information). No predicted-cost factory exists yet; `docs/travel_matrix.md` has a 6-line
wrapper, checked against WorldTravel.
### Heuristic debug check
With a heuristic, `update_edge_cost` warns (`HeuristicWarning`) when a road becomes cheaper than the
heuristic allows, because routes may then not be optimal. With `make_heuristic(G)` that means below
free-flow time. R6's multipliers are never below 1 and spikes are 1.2x or more, so it should never fire.

## Multi-stop routes (R7, Week 3)
D* Lite plans to one goal, so `MultiStopPlanner` keeps one D* Lite per leg (vehicle -> stop 1 -> stop 2 ...).
Road changes go to every remaining leg; when the vehicle reaches a stop, that leg is dropped.

```python
p = MultiStopPlanner.from_networkx(G, start, [s1, s2, s3], heuristic=make_heuristic(G))
p.path(); p.path_cost()          # whole route through all stops; [] / inf if a stop is unreachable
p.close_edge(u, v)               # also update_edge_cost / reopen_edge, sent to every leg
p.move_start(node)               # vehicle moved; legs advance when a stop is reached
p.unreachable_stops()            # stops a closure has cut off
```

## D* Lite in R1's simulator (R7, Week 3)
`src/search/sim_replanner.py` connects D* Lite to `DeliverySimEnvironment` **without changing R1's code**:

```python
from src.search.sim_replanner import SimReplanner
replanner = SimReplanner(env, heuristic=make_heuristic(world.graph()))
replanner.register(vehicle, stops=[o.node for o in orders])   # sets vehicle.remaining_route
env.add_vehicle(vehicle, orders)
env.run()
```
- Costs follow decision D10: predicted travel time x live spike multiplier, `inf` while closed.
- It listens to `env.subscribe`. On every closure or spike, each vehicle's planner is updated and its
  `remaining_route` replaced. A vehicle on a road cannot turn back, so it replans from the end of that road.
- Each replan is logged as a new `replan` event: `{"trigger", "edge", "from_node", "route_found",
  "unreachable_stops", "expanded", "cpu_seconds"}` (CPU time per D9). To add to `docs/log_schema.md` with R1/R8.
- Closures and spikes have no "ended" event, so roads that had one are re-checked at every later event.

**Suggested change for R1** (replaces the "wait 60 s" `TODO(R7)` in `src/sim/environment.py`, for a
closure that is already there when the vehicle reaches it):

```python
from src.search.sim_replanner import reroute, stops_from_route
...
if self.world.is_blocked(u, v, key, self.get_current_time()):
    stops = stops_from_route([v] + vehicle.remaining_route, {o.node for o in pending})
    new_route = reroute(self.world, vehicle, stops, self.get_current_time())
    if new_route:                                  # None: no way round now, so wait as before
        vehicle.remaining_route = new_route
        continue
```

## F3: D* Lite vs A* replanning by number of changed roads (R7, Week 3)
`python -m src.search.benchmark_replan` writes `reports/dstar_benchmark.csv` (one row per trial) and
`reports/figures/F3_dstar_speedup.png`. 20 trips (seed 7, at least 10 roads), k in {1 ... 500} changed
roads (D11 mix: 3/7 closures, else spikes x1.2-3), R2's heuristic in both planners, `time.process_time()`.
Every D* Lite answer is checked against A* during the run.

| Roads changed | Anywhere on the map | On route, near vehicle | On route, near goal |
| --- | --- | --- | --- |
| 1 | 58x faster (0.08 vs 4.1 ms) | 5.5x | 1.0x |
| 10 | 23x | 0.8x | 1.1x |
| 50 | 3.5x | 0.9x | 1.0x |
| 100 | 1.4x | 0.8x | 0.9x |
| 500 | 0.5x (slower) | 0.5x | 0.5x |

Median speed-up = A* CPU / D* Lite CPU. What it shows, honestly:
- **Changes away from the route are almost free** for D* Lite (most do not touch its search), so a few
  random disruptions, as in D11, give 20-60x speed-ups.
- **Changes on the route near the goal give no speed-up.** D* Lite searches backwards from the goal, so a
  change there invalidates most of its g-values and it redoes about a full search.
- **Changes on the route near the vehicle** help while few (5x for 1 road) but not beyond about 5 roads,
  because the new route is far from the old one.
- **Hundreds of changes at once:** D* Lite is about 2x slower than A*, because repairing costs more per
  node than searching fresh. Above that a fresh plan (new `DStarLite`) is the better choice.
- Rough, single-machine figures; rerun with `--trips` and other seeds for the report.
