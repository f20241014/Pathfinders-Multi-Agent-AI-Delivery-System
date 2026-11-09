# R4 allocation and centralized baseline

Catch-up implementation authored in November 2026, organized by planned week.
No commit dates or experimental results are backdated.

## Week 1: model and toy CVRP

Run `python -m src.allocation.toy_cvrp` and `python -m pytest tests/test_allocation_w1.py`.
Install the isolated dependencies with `pip install -r requirements-r4.txt`.

Cost is marginal **travel seconds** for insertion into an open route (no implicit
return to depot). Waiting and service affect feasibility, not the travel objective.
Capacity uses the simulator's accumulated-load semantics: current load plus all
remaining demands <= capacity. No reload/unload model is invented here.
Windows constrain service start, matching the existing simulator. Higher numeric
priority has larger drop penalty (3 > 2 > 1). R3 can inject a `(bool, trace)`
feasibility function; local capacity/window checks are always retained.

CNP announces to m vehicles, receives one bid per feasible contractor, awards
one winner if any: m + bids + (1 if awarded else 0). This is allocation traffic,
not R5 negotiation traffic; no award is sent for an unassignable order. Tie-break
by vehicle ID. These counting and priority conventions are proposals for team review.

## Primary references checked during implementation

- https://developers.google.com/optimization/routing/cvrp
- https://developers.google.com/optimization/routing/vrptw
- https://developers.google.com/optimization/routing/penalties
- https://developers.google.com/optimization/routing/routing_options
- Smith (1980), Contract Net Protocol: https://doi.org/10.1109/TC.1980.1675516

Contract Net is announcement, bid, award; cheapest marginal insertion is a local
heuristic, not a guarantee of globally optimal fleet allocation. OR-Tools is a
bounded-search reference, not a certified optimum or mathematical upper bound
on delivery quality. Team/buddy review remains outstanding until actually done.

## Week 2: insertion and Contract Net

`ContractNet.allocate(order, states, now)` mutates only the winning state orders.
Bids are cheapest feasible insertion deltas; duplicate awards raise ValueError.
An emit callback counts every recipient; failed allocation sends announcements
but no bid or award. Tests hand-check insertion, ties, windows, capacity, R3 hook,
unreachable nodes, and message accounting.

## Week 3: centralized partial-state CVRPTW

`CentralVRP(travel, time_limit_s=2).resolve(states, orders, now)` returns routes,
explicit failed IDs, objective (integer travel plus drop penalties), float travel,
CPU and 2N messages. Snapshot mid-edge vehicles at their next node and known
edge-exit time; exclude delivered/actively served orders. Open routes use a
zero-cost synthetic sink. Distinct visit indices support co-located orders.
Times round up to seconds, upper windows round down, demand rounds up to 0.001
units, residual capacity down. This conservatism can reject borderline float
solutions. Optional R3 feasibility is checked after solving; a rejected vehicle
route is failed, not silently accepted. Custom rules are not encoded in OR-Tools
and may reduce reference quality. Solver time limits are wall time; measured
CPU includes model construction and extraction. No optimality certification.

## Week 4: mode/event integration boundary

`AllocationController(world, states, mode, emit).event(now, new_order=None)`
wires centralized re-solving and decentralized CNP to existing World/Vehicle/Order
interfaces. R1 can call it on each observed event; populate `busy` for committed
edges or service, remove active/delivered orders from pending queues, and update
live position/load on completion. Snapshots do not mutate physical positions.
WorldTravel caches per road-class profile and source, using forecasts plus only
current closures/spikes for both planners. Rebuild on events/forecast updates.
This is frozen-snapshot routing, not FIFO time-dependent optimization.
Full-mode R4 allocation is identical to independent; R5 negotiation and R7
D* Lite remain their owners' responsibility. The existing R1 default runner is
unchanged; the R4 executable integration harness follows in Week 5.

## Week 5: executable integration and quality gate

`python -m src.allocation.sim_runner --mode centralized` runs a synthetic
SimPy smoke scenario with dynamic orders, real Vehicle/Order/World and JSONL
interfaces. Modes independent/full use the same CNP; full is an allocation-only
smoke mode, not a substitute for the R5/R7 complete experiment. The opt-in
AllocationSimulation subclass supports event replanning, committed edge/service
protection, explicit horizon failures, road restrictions and accumulated load.
Final allocation_summary is authoritative; the inherited sim_complete row is
written before horizon reconciliation. Event feed and physical traversal remain
R1-owned. Tests inject a closure during travel and check exact-once terminals.

An independent exhaustive checker enumerates tiny assignments/drop choices/stop
permutations and tests the solver objective at three capacities. This establishes
small-case correctness, not near-optimality for the full Hyderabad scenario.
