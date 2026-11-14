# R3 · CSP for order-to-vehicle feasibility (Week 3)

Code: `src/kr/csp.py` · Tests: `tests/test_csp.py` · Benchmark: `src/kr/csp_benchmark.py` -> `docs/csp_pruning.md`

## Formulation

| Part | Definition |
|---|---|
| Variables | `X_o` for each order `o` in the batch being assigned |
| Domains | `D_o` = vehicles that can serve `o` together with what they already carry (`committed[v]`). Unary checks: KR-11 release, KR-1 capacity, KR-8 window, KR-10 shift, reachability |
| Binary constraints | for orders `o, p` and vehicle `v` in both domains: `X_o = v and X_p = v` only if `v` can serve `committed[v] + {o, p}`. These arcs are what AC-3 works on |
| Global constraint | everything assigned to `v` must be serviceable in **some** stop order (capacity, windows, shift). Checked exactly when a value is assigned |

"Serviceable in some stop order" is itself a search (`find_sequence`): depth-first over stop orders, earliest
deadline first, with dominance pruning (same stops left and same last stop reached later is never better) and a
look-ahead (stop if a remaining stop can no longer make its deadline). Exact up to 9 stops. The rule engine's
KR-13y calls the same function, so there is one implementation of it.

Units are the same as the rules: times in seconds since midnight (search starts at 06:00 unless `t_now` is
given); an order with R1's default window (0.0, 86400.0) has no time window.

## Search

- **Backtracking** over the variables.
- **MRV**: pick the order with the fewest vehicles left; ties go to the order with the most unassigned neighbours (degree).
- **LCV**: try first the vehicle that rules out the fewest options for neighbouring orders.
- **Forward checking**: after `X_o = v`, remove `v` from each neighbour `p` if `v` cannot also serve `p`.
- **AC-3** before search; optionally **MAC** (AC-3 on the unassigned orders after every assignment, using the vehicle's current load).

## Why AC-3 is sound here

The binary constraint is a necessary condition of the global one: if `v` cannot serve `{o, p}` it cannot serve any
superset. So AC-3 never deletes a value that appears in a solution. `test_ac3_never_removes_a_value_used_by_a_solution`
checks this against brute force on 25 random instances.

## Validation

- CSP result = brute force (every assignment x every stop order) on 25 random instances, for all 5 configurations.
- CSP result = `python-constraint` on 15 random instances.
- `find_sequence` = trying every permutation on 40 random instances.

## Pruning results (table: `docs/csp_pruning.md`)

- **Forward checking is the big win.** On 12 orders x 4 vehicles it cuts mean nodes from 46,342 to 6,140 (about 7.5x),
  and plain backtracking hit the 100,000-node limit on 11 of 30 instances while FC never did.
- **MRV alone changes nothing.** Without FC no domain ever shrinks, so every variable ties on "fewest values left"
  and MRV falls back to the static order. MRV only pays off together with FC (the FC rows already include MRV).
- **AC-3 once at the root adds nothing here.** Our binary constraint ("o and p may share vehicle v only if v can
  serve both") is a not-equal style constraint: it can only remove a value when the other order's domain is a single
  vehicle, which is rare before search starts. Same reason AC-3 is weak on graph colouring.
- **MAC (AC-3 after every assignment, with the vehicle's current load) prunes a further ~35-40%** of nodes over FC
  (6,140 -> 3,839 on 12 x 4), but each node costs more, so wall-clock time is higher at these sizes.
  Trade-off: fewer nodes vs more constraint checks per node.
- **LCV** reorders values; it does not change node counts on infeasible instances (every value is tried anyway)
  and adds constraint checks.
- Consequence for the system: the CSP is used on small sub-problems (one new order -> `eligible_vehicles`, or a
  handful of orders after a disruption), never as one global problem over 300 orders.

## How other modules use it

- **R4 (bidding filter):** `eligible_vehicles(order, vehicles, travel_time, t_now, committed)` -> vehicles allowed to bid,
  with rule traces for the rejected ones (`explain=True`). Or plug the rules into R4 directly:
  `ContractNet(travel, feasibility=r4_feasibility_hook(travel))` (`src/kr/adapters.py`, with travel times, so
  KR-8/KR-10 run), or `adapt_r3_feasibility(run_feasibility_engine)` (no travel times: capacity, release, shift duration only).
- **Travel times:** `travel_time_from_matrix(TravelTimeMatrix(G, factory), nodes)` turns R2's matrix into `travel_time(u, v, t)`.
- **Batch after a disruption:** `solve_batch(vehicles, orders, travel_time, t_now, committed)`.

## Viva answers

- **AC-3:** queue all arcs `(Xi, Xj)`; `revise` removes values of `Xi` with no supporting value in `Xj`; if `Xi` changed,
  re-queue every `(Xk, Xi)`. Complexity `O(e d^3)`: each arc re-enters the queue at most `d` times, each revise is `O(d^2)`.
- **Why MRV:** fail first. The variable with the fewest values is the most likely to fail, so failing early prunes the
  biggest subtrees. It needs forward checking to work, since without it domains never shrink (see the benchmark).
- **Forward vs backward chaining:** the rule engine is forward chaining: it starts from the facts (orders, loads, ETAs)
  and derives violations. Backward chaining starts from a goal and works back, which suits "prove X" queries, not
  "what follows from these facts".
- **Limits:** above 9 stops per vehicle the sequence check falls back to priority-first / EDF orders, which can say
  "no" when a stop order exists (never a false "yes"). The global CSP is not used for 300 orders.