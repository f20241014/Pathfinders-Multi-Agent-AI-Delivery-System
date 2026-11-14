# KR&R — Ontology and Rules

Owner: R3 · Reviewer: R8 (buddy) · Code: `src/kr/ontology.py`, `src/kr/rules.py`, `src/kr/engine.py`

Rule ids are **KR-n** so they never clash with role names (R1-R8).

## 1. Ontology

### Units

R3's code uses these units. They are proposed to R1 for `docs/DECISIONS.md` (R1 owns that file) and
are not team-wide until R1 records them there.

| Quantity | Unit |
|---|---|
| `demand`, `capacity`, `load` | abstract capacity units, same unit for all three (D2); 1 unit = median Amazon package volume |
| `tw_start`, `tw_end`, `release_time`, `shift_end` | seconds since midnight, inside 06:00-10:00 (21600-36000 s, D4) |
| `service_time` | seconds (a duration) |
| no time window | `tw_start = 0.0`, `tw_end = 86400.0` (R1's `Order` defaults, never `None`); `ontology.tw_of()` reads exactly that pair as "no window" |

The 20/50/30 express/standard/economy split and the 30% share of dynamic orders are our
assumptions (the Amazon data has no priorities): `PRIORITY_SPLIT`, `DYNAMIC_SHARE` in
`src/data/orders_from_amazon.py`.

### Entities and attributes

| Entity | Attributes | Source |
|---|---|---|
| **Vehicle** | id, depot_node, capacity, current_node, load, allowed_road_classes, remaining_route (R1's `src.sim.models.Vehicle`) + vehicle_class ∈ {small, large}, shift_end (added in `src.kr.ontology.Vehicle`) | R1 + R3 |
| **Order** | id, node, demand, priority ∈ {1 express, 2 standard, 3 economy}, tw_start, tw_end (or None), service_time, release_time | R1's `src.sim.models.Order` |
| **Road** (edge u→v) | road_class / highway, length, free_flow_time, blocked(t) | R2 graph, R1 events |
| **Zone** | id, set of nodes, banned vehicle classes, restricted hours | R3 class; zones of our map TODO(R2) |

### Relations
- assigned_to(Order, Vehicle) — at most one vehicle per order
- located_at(Order, Node), in_zone(Node, Zone)
- precedes(Order a, Order b, Vehicle) — stop order in a route

### Derived facts (rules put these into working memory)
- `load_total` = vehicle.load + Σ demand → `capacity_ok`
- `service_total` = Σ service_time → `shift_duration_ok`
- `release_ok`
- `sequence` (needs capacity_ok, release_ok, shift_duration_ok)
- `stop` (arrival, start, departure per order) and `return` (time back at the depot), from a sequence + travel times

## 2. Rules

**H** = hard (violation makes the plan infeasible), **S** = soft (preference).

| # | Rule | Type | Where |
|---|---|---|---|
| KR-1 | A vehicle's total demand (load already on board + new orders) may not exceed its capacity. | H | `rules.py` |
| KR-2 | A vehicle with zero remaining capacity does not bid on new orders. | H | follows from KR-1; bidding is TODO(R4) |
| KR-3 | A vehicle may only use roads whose class is in its allowed road classes (large vehicles avoid `residential`, `living_street`, `service`, `unclassified`). | H | `road_allowed`; in planners via `planner_rules.RoadRules` |
| KR-4 | No vehicle may enter an edge while it is closed. | H | `road_allowed`; planners via `RoadRules` / R1's world |
| KR-5 | A vehicle may not traverse a one-way edge against its direction. | H | the graph is directed (R2) |
| KR-6 | Large vehicles may not enter a restricted zone during its restricted hours. | H | `road_allowed`, `RoadRules`; zones TODO(R2) |
| KR-7 | If a vehicle arrives before tw_start (or release_time), it waits. | H | `rules.py` (ETA) |
| KR-8 | Service must start no later than tw_end. | H | `rules.py`, needs travel times |
| KR-9 | Departure from a stop = service start + service_time. | H | `rules.py` (ETA) |
| KR-10 | Every vehicle must be back at its depot by shift_end. | H | `rules.py`, needs travel times |
| KR-10a | Shift duration: even with zero travel, all service must end before shift_end. | H | `rules.py` (no travel times needed) |
| KR-11 | An order cannot be assigned or served before its release_time. | H | `rules.py` |
| KR-12 | Each order is served exactly once, by exactly one vehicle. | H | allocation audit, TODO(R4/R5) |
| KR-13 | Express (priority 1) stops come before priority 2 and 3, unless that breaks a hard time rule. | S | `rules.py`; planners via `planner_rules.priority_stops` |
| KR-13x | If the priority order breaks KR-8/KR-10, retry earliest deadline first. | override | `rules.py` |
| KR-13y | If that fails too, search every stop order (up to 9 stops). | override | `rules.py` -> `csp.find_sequence` |
| KR-14 | An express order must be assigned within X minutes of release, otherwise it is re-auctioned. | S | TODO(R4) |
| KR-15 | If no vehicle can serve an order, mark it `rejected` with the rule(s) that blocked every vehicle. | H | `violated_rules()` gives the reasons; marking TODO(R4) |
| KR-16 | When a new closure invalidates a planned route, the vehicle must replan before continuing. | H | TODO(R7) |

## 3. Conflict resolution between rules

Rules fire in salience order (highest first); a higher class can veto a lower one:

1. **Safety / legality**: KR-4, KR-5, KR-3, KR-6, KR-11
2. **Physical limits**: KR-1, KR-2, KR-10a
3. **Commitments**: KR-8, KR-10, KR-12 (KR-7, KR-9 are definitions used by these)
4. **Preferences**: KR-13, KR-14

Example: KR-13 wants the express stop first, but that makes a standard order miss its tw_end (KR-8).
KR-8 is higher, so the order that respects the window wins and the trace says `KR-13 overridden by KR-8`.

## 4. Explanation trace (real output)

```
LOAD: load_total = 0 on board + 5 new = 5
KR-1: ok load 5/10
KR-13: sequence by priority tier: E -> S
ETA: KR-7/KR-9 ETAs for [E, S], back at depot 22800s
KR-8: FAIL S service starts 22680s > tw_end 21800s
KR-10: ok back at depot by 22800s
KR-13x: KR-13 overridden by KR-8: retry earliest-deadline-first S -> E
ETA: KR-7/KR-9 ETAs for [S, E], back at depot 22800s
KR-10: ok back at depot by 22800s
FEASIBLE: S -> E
```

## 5. Open questions
- R1 to record the units above in DECISIONS.md.
- Two vehicle classes, or a homogeneous fleet first (D2 says homogeneous first, so KR-3/KR-6 only matter once large vehicles exist)?
- Value of X in KR-14 (suggest 10 sim-minutes). TODO(R4)
- Which Secunderabad areas are KR-6 zones. TODO(R2)