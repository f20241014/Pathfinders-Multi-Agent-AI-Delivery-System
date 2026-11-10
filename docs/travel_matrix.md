# Travel-time matrix (R2, Week 3)

`src/search/travel_matrix.py` gives the travel time in seconds between every pair of N nodes, at one time t.
The allocation and scheduling code needs these numbers: how long a vehicle takes to reach a pickup, and to
get from one stop to the next.

## What it is
- `single_source_costs(G, source, cost_fn, targets=None)`: Dijkstra written from scratch with `heapq` (no
  networkx search). It returns `{node: seconds}`. With `targets` given, it stops as soon as every target is
  settled. A blocked edge (cost `math.inf`) is never used, and a node that cannot be reached gets `math.inf`.
- `TravelTimeMatrix(G, cost_fn_factory)`: `travel_time_matrix(nodes, t)` returns an N x N list of lists, where
  `m[i][j]` is the time from `nodes[i]` to `nodes[j]`. Roads are one-way, so `m[i][j]` and `m[j][i]` can differ.
  The diagonal is 0, and `math.inf` means no route exists.
- Each row (one Dijkstra run from one source) is cached under the key `(t, source)`. A repeated call is then a
  dictionary lookup. If an earlier early-exit run did not settle a requested target, the row is computed again.
- Counters: `hits` and `misses` count rows, one per source per call. `expanded` is the total number of nodes
  popped by all Dijkstra runs. `clear_cache()` forgets every row.

## Snapshot convention
Every edge is costed once, at the time t of the request: `cost_fn_factory(t)` gives the `cost_fn` used for
the whole matrix. Traffic does not change while the vehicle drives. R4's `WorldTravel` uses the same
convention. For entry-time costs use `time_dependent.py` (`dijkstra_td`, `astar_td`).
The cache does not watch the world. After a new closure or spike *at the same t*, call `clear_cache()`.
A different t is always a new row anyway.

## API
```python
from src.search.travel_matrix import TravelTimeMatrix
tm = TravelTimeMatrix(world.G, cost_fn_factory)    # cost_fn_factory(t) -> cost_fn(u, v, data)
m = tm.travel_time_matrix(nodes, t=28800)          # 08:00, seconds; m[i][j], inf if no route
tm.hits, tm.misses, tm.expanded                    # cache counters, nodes expanded so far
```
The `cost_fn(u, v, data)` convention is the one used by `dijkstra.py`. For free-flow times, pass
`lambda t: free_flow_cost`.

## Which cost function to pass
**For planning, pass a cost function built from PREDICTED times plus the live closure/spike feed (as R4's
WorldTravel does), not `World.cost_fn_at`.** `cost_fn_at` uses the actual `edge_time`, which is ground truth
for the simulator and metrics only. Planning with it would give agents knowledge of the future and break
D10 (all conditions see the same information).

The repo has no predicted-cost factory yet. This 6-line wrapper builds the same edge cost as
`WorldTravel.graph_for`: a road closed at t is `inf`, otherwise `predicted_time(u, v, t)` x `spike_multiplier(u, v, t)`.
```python
def predicted_cost_fn_at(world, t):
    def cost(u, v, data=None):
        if world.is_blocked(u, v, t):
            return math.inf
        return world.predicted_time(u, v, t) * world.spike_multiplier(u, v, t)
    return cost
```
Use it as `TravelTimeMatrix(world.G, lambda t: predicted_cost_fn_at(world, t))`. As a read-only check (script
not committed), on the same 10 pairs as below with R6 traffic at t = 28800 it gave the same time as
`WorldTravel` on 10/10 pairs. `WorldTravel`'s per-vehicle road-class filter is not included.

## Measured on the full Secunderabad graph
The graph has 2,377 nodes and 6,056 edges. I used 20 random nodes (seed 42) at t = 28800 (08:00). Each
setting ran 5 times with a fresh matrix each time, and the table shows the medians from `time.perf_counter()`.
Measured on one Windows laptop with Python 3.14.5; other machines will give different numbers.

| Cost function | First call | Second call (same nodes, same t) | Speed-up |
| --- | --- | --- | --- |
| free-flow (`free_flow_cost`) | 145 ms | 0.14 ms | about 1,000x |
| `FakeWorld.cost_fn_at` (no traffic) | 352 ms | 0.14 ms | about 2,500x |
| `World.from_defaults().cost_fn_at` (R6 traffic; timing only, not for planning) | 416 ms | 0.14 ms | about 3,000x |

The 5 first-call times were within 3% of each other (free-flow: 141.9-145.7 ms).

**My prediction, made before measuring:** about 2 minutes for the first call, and the second call 2-3x faster.
- First call: wrong by almost 1,000x. 20 Dijkstra runs on 2,377 nodes take a few hundred milliseconds, not minutes.
- Second call: far more than 2-3x faster. With the same nodes and the same t, every row is a cache hit: 20 hits,
  0 nodes expanded. The second call only builds the 20 x 20 list from dictionaries.
- Early exit hardly helps for 20 random targets. The first call expanded 46,277 nodes, about 2,314 per
  source, which is almost the whole graph each time. Spread-out random targets mean one of them is usually
  near the far edge. Early exit helps when the targets are close to the source.
- `World.cost_fn_at` is 2.4-2.9x slower than the free-flow lookup. It calls `edge_time`, which looks up the
  fastest key, closures, spikes and the traffic multiplier for every edge relaxation.

## Check against R4's WorldTravel (read-only, script not committed)
I compared 10 random (source, target) pairs (seed 1, t = 28800) between this matrix and
`WorldTravel(world, t)(vehicle, s, d)`, with no road-class restriction:
- `FakeWorld` (no traffic model): **10/10 agree** (largest difference 0.000 s).
- `World.from_defaults()` (R6 traffic), matrix built with `World.cost_fn_at`: **0/10 agree**. `WorldTravel`
  was 1.5-4.5% higher (largest difference 15.6 s). This is not a bug in either module. They use different
  costs: `WorldTravel` uses R6's **forecast** (`predicted_time` x spikes), while `World.cost_fn_at(t)` uses
  the **actual** `edge_time` (true traffic x spikes). They only agree when there is no traffic model. That
  difference is exactly why planners should not use `cost_fn_at` (see "Which cost function to pass"). With
  the `predicted_cost_fn_at` wrapper above, the same 10 pairs agree 10/10.

## Who can use it
- R4 (OR-Tools routing) needs an N x N time matrix of depot, pickups and drops, which is exactly this output.
- R3 (CSP) can use it to check time windows: can vehicle k reach stop j before it closes?
- R4 currently uses its own `WorldTravel`, so this module is an **offer, not a dependency**. Nothing in
  `src/allocation` imports it, and nothing outside `src/search` changed.

## Tests
`tests/test_travel_matrix.py` (7 tests):
- matches `networkx.single_source_dijkstra_path_length` on `secunderabad_small` for 20 random nodes (seed 7);
- a full run returns a value for every node;
- toy graph: the diagonal is 0, unreachable gives `inf`, and the matrix is asymmetric;
- a blocked edge changes the result and is never used;
- the second call with the same (nodes, t) is 20 hits with 0 nodes expanded, and a new t is a miss;
- the factory receives t;
- early exit gives the same numbers as the full run.
