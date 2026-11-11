# KR&R — Ontology and Rules (draft v0.1, Week 1)

Owner: R3 · Reviewer: R8 (buddy) · Status: draft for the Week 1 interfaces freeze

## 1. Ontology

### Entities and attributes

| Entity | Attributes | Source |
|---|---|---|
| **Vehicle** | id, depot_node, capacity (abstract units), vehicle_class ∈ {small, large}, allowed_road_classes, shift_start, shift_end, current_node, load, remaining_route | R1 dataclass |
| **Order** | id, node, demand, priority ∈ {1 express, 2 standard, 3 economy}, tw_start, tw_end (or none), service_time, release_time | R3 (frozen interface) |
| **Road** (edge u→v) | highway_class, length, oneway, free_flow_time, slot_capacity kₑ, blocked(t) | R2 graph, R1 events |
| **Zone** | id, set of nodes, restrictions (e.g. no large vehicles 08:00–10:00) | R3 config |
| **Depot** | node, opening hours | config |

### Relations
- assigned_to(Order, Vehicle) — at most one vehicle per order
- located_at(Order, Node), in_zone(Node, Zone)
- traverses(Vehicle, Road, t) — from the planned Route
- precedes(Order a, Order b, Vehicle) — stop order in a route

### Derived facts (computed, put into working memory)
- arrival(v, o), departure(v, o) = max(arrival, tw_start) + service_time
- remaining_capacity(v) = capacity − Σ demand of assigned, undelivered orders
- return_time(v) = time back at depot

## 2. Rules (plain language)

Each rule is tagged **H** (hard: violation makes a plan infeasible) or **S** (soft: preference, adds cost).

| # | Rule | Type | Fires when |
|---|---|---|---|
| R01 | A vehicle's total assigned demand may not exceed its capacity. | H | assign / insert |
| R02 | A vehicle with zero remaining capacity does not bid on new orders. | H | allocation |
| R03 | A vehicle may only use roads whose class is in its allowed road classes (large vehicles avoid `residential`, `living_street`, `service`). | H | planning (`road_allowed`) |
| R04 | No vehicle may enter an edge while it is closed. | H | planning, replanning |
| R05 | A vehicle may not traverse a one-way edge against its direction. | H | planning (graph is directed) |
| R06 | Large vehicles may not enter a restricted zone during its restricted hours. | H | planning, time-dependent |
| R07 | If a vehicle arrives before tw_start, it waits until tw_start. | H | ETA computation |
| R08 | Service must start no later than tw_end; otherwise the insertion is infeasible. | H | insert / CSP |
| R09 | Departure from a stop = service start + service_time. | H | ETA computation |
| R10 | Every vehicle must be back at its depot by shift_end. | H | insert / CSP |
| R11 | An order cannot be assigned or served before its release_time. | H | allocation |
| R12 | Each order is served exactly once, by exactly one vehicle. | H | allocation, audit |
| R13 | On a route, express (priority 1) stops come before priority 2 and 3 stops, unless that would break a time window. | S | sequencing |
| R14 | An express order must be assigned within X minutes of release; if not, it is escalated (re-auctioned to all vehicles). | S | allocation |
| R15 | If no vehicle can serve an order, mark it `rejected` and record which rule(s) blocked every vehicle. | H (bookkeeping) | allocation |
| R16 | When a new closure invalidates a planned route, the affected vehicle must replan before continuing. | H | event handling |

## 3. Conflict resolution between rules

Rules fire in salience order (highest first); a higher class can veto a lower one:

1. **Safety / legality** — R04, R05, R03, R06
2. **Physical limits** — R01, R02
3. **Commitments** — R08, R10, R11, R12 (R07, R09 are definitions used by these)
4. **Preferences** — R13, R14

Example: R13 wants the express stop first, but that makes a standard order miss its tw_end (R08). R08 is higher, so the order that respects the window wins and the trace says `R13 overridden by R08`.

## 4. Explanation trace format (for Week 2 engine)

```
feasible(V3, {O17, O22}) -> False
  fired: R01 ok (load 7/10)
  fired: R03 ok
  fired: R08 FAIL  O22 arrival 10:42 > tw_end 10:30
```

## 5. Open questions for the Week 1 meeting
- Capacity units: map Amazon cm³ to abstract units (e.g. 1 unit = median package volume)? → affects D2/D3
- Do we have two vehicle classes, or homogeneous fleet first (D2 says homogeneous first → R03/R06 only matter once large vehicles exist)?
- Value of X in R14 (suggest 10 sim-minutes).
- Which Hyderabad zone gets the R06 restriction (pick once R2 fixes the map, D1).