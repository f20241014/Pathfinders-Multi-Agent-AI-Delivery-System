# R3 · Week 4: rules in the planners

Code: `src/kr/planner_rules.py` · Tests: `tests/test_planner_rules.py`

Three things the plan asks of R3 this week, and the one line each owner adds to use them.
No R1/R2/R4/R7 file is changed by R3; every hook below is tested against the real classes.

## 1. Rules → blocked edges (KR-3 road class, KR-4 closures, KR-6 zones)

Every planner already treats "cost is inf" or "`world.is_blocked(...)` is True" as a road it may not
use. `RoadRules` answers those two questions per vehicle:

```python
from src.kr.planner_rules import RoadRules, zones_from_config
rules = RoadRules(world.graph(), zones_from_config(cfg))     # once per run
```

| Planner | Owner | Hook |
|---|---|---|
| `astar`, `dijkstra`, `k_shortest_paths`, `TravelTimeMatrix` | R2 | `cost_fn=rules.cost_fn(vehicle, base_cost_fn, t)`; matrix: `TravelTimeMatrix(G, rules.cost_fn_factory(vehicle, base_factory))` |
| `ReplanningAgent` / `AgentPlanner` (D* Lite) | R7 | in `AgentPlanner.register`: `ReplanningAgent(vehicle, rules.view(self.env.world, vehicle), stops, ...)` instead of `self.env.world` |
| `WorldTravel` (CNP and OR-Tools paths) | R4 | `WorldTravel(rules.view(world, vehicle), now)` |
| R1's `world.cost_fn_at(t)` | R1 | `rules.view(world, vehicle).cost_fn_at(t)` |

`rules.view(world, vehicle)` is R1's World as that vehicle may use it: rule-forbidden roads look
closed (`is_blocked`, `edge_time`, `cost_fn_at`), everything else is the real world. Never hand a
view to R1's environment itself, because the environment moves vehicles on the real world.

`rules.blocked_edges(vehicle, t)` and `rules.explain_edge(vehicle, u, v, t)` give the reason
("KR-3 road class 'residential' not allowed") for logs and the demo.

**Vehicle class.** R1's `Vehicle` has no `vehicle_class`. A vehicle whose `allowed_road_classes` has no
narrow class (`residential`, `living_street`, `service`, `unclassified`) counts as **large**, so KR-6
zones apply to it. Scenario files write `allowed_road_classes` for large vehicles (section 3).

**Consistency with R4.** R4's `WorldTravel` keeps an edge when *any* of its OSM classes is allowed;
R3's rules use the *most restrictive* class of a merged edge (and R2's `road_class` attribute when
present). On the Secunderabad map this only matters for merged edges. Using `rules.view` in
`WorldTravel` makes both modes plan on the same roads. TODO(R4).

**What it means on the real map.** 78% of Secunderabad's roads are residential. A large vehicle
can reach only 675 of 2,377 nodes (the largest strongly connected part of the non-narrow roads).
That is why the fleet is small-only by default (D2), and why mixed fleets put depots on that part.

## 2. Priority ordering in the planners (KR-13, with KR-8 / KR-10 overrides)

```python
from src.kr.planner_rules import priority_stops
stops, result = priority_stops(vehicle, orders, travel_time, t_now)
planner.register(vehicle, orders, stops=stops)      # R7's register already accepts stops=
```

Express stops first; if that breaks a window or the shift end, the rule engine's KR-13x
(earliest deadline first) and KR-13y (exact search) choose the order. If nothing is feasible the stops
still come back in plain priority order, with `result["feasible"] == False` and the reasons.
`travel_time(u, v, t)` can be `travel_time_from_matrix(...)` (Week 3) on the rule-aware matrix.

Visible difference (tests `test_express_order_is_delivered_first_in_r1_sim` and
`test_without_priority_stops_the_listed_order_is_driven`): same vehicle, same two orders in R1's
simulator with R7's planner. With `priority_stops` the express order is delivered first; without it
the order list is driven as given.

TODO(R7): when `stops is None`, use `priority_stops(...)[0]` in `AgentPlanner.register`.
TODO(R4): order each vehicle's stops with `priority_stops` (or `sort_orders_by_priority`) after allocation.

## 3. Explanation trace in the run log

```python
from src.kr.planner_rules import log_kr_trace
log_kr_trace(env, t, vehicle.id, result, context="register")   # or a MetricsLogger
```

Writes one row in R1's JSONL format: `event = "kr_check"`, `agent_id = vehicle`,
`payload = {feasible, violated, sequence, trace, context}`. TODO(R1): add `kr_check` to
`docs/log_schema.md`.

## 4. Final scenario configs

See `docs/scenarios.md`. Week 4 adds `--large-share` (mixed fleets, rule-aware servable check).