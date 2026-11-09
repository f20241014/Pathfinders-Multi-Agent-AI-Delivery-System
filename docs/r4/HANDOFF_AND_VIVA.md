# R4 Week 6 handoff and viva guide

## Integration contract

- Public API: ContractNet.allocate, CentralVRP.resolve, AllocationController.event.
- Shared types are src.sim.models.Order/Vehicle; VehicleState adds pending orders
  and available_at. Route outputs here are ordered Order objects, not road paths;
  WorldTravel.path expands each next stop into road nodes for R1/R7.
- R1 owns clock/movement/terminal lifecycle. Call controller for every observed
  incident, new order and forecast refresh. Pass busy state for edge/service
  commitment. Never remove the currently traversed edge or active service.
- R3 injects feasible(vehicle, orders) -> (bool, trace). Base capacity/windows are
  always enforced. Custom constraints are postchecked in centralized mode; that
  can weaken baseline quality. Encoding them inside the solver is future work.
- R2 shortest-path snapshot matrices are cached by source/road profile. Current
  World prediction plus current closure/spike feed is used identically in both
  planners; actual future traffic/incident expiry is not queried for planning.
- R5 allocation messages are separate from negotiation; point-to-point count=1.
  Centralized 2N messages includes idle vehicles. Independent/full CNP counting
  is announcements + feasible bids + award, no failed award. Agree these rules
  with R5 before team merge; no agreement is fabricated here.
- R8: logs use SimulationLogger JSONL; allocation_complete includes CPU/messages.
  Failed orders must be included in quality comparisons, not silently discarded.
  sim_runner is an allocation integration harness, not the final three-mode study.

## Frozen R4 defaults for review

Two-second solver wall budget; one routing search worker; travel objective plus
100000 * priority per dropped order; priority 3 highest; open routes; accumulated
load; service-start windows; conservative seconds/0.001-unit scaling; no reloads.
Pilot study config and hash live in reports/r4. Do not tune using final test seeds.
Timing results vary with hardware; time-limited search can vary even for a seed.
Report quality at the chosen budget, never call it a proof of near-optimality.

## Viva prompts and answer outlines

1. Contract Net: manager announces, feasible contractors bid marginal insertion
   travel cost, lowest bid wins. Local decisions can miss globally better plans.
2. Insertion: enumerate every position, simulate travel/wait/service, check
   capacity/windows/custom rules, minimize travel delta. Waiting is feasibility,
   not part of the travel objective. Tie-break position then vehicle ID.
3. VRP: assignment and visit ordering combine an NP-hard optimization. OR-Tools
   constructs PATH_CHEAPEST_ARC then uses GUIDED_LOCAL_SEARCH within a fixed limit.
4. Capacity: existing accumulated load reserves space; remaining demands cannot
   exceed residual capacity. Busy service reserves demand before completion.
5. Partial state: en-route vehicles cannot reverse; start their snapshot at next
   node and edge-exit availability. Active service and delivered orders excluded.
6. Fairness: same information/travel model/constraints; account for 2N centralized
   messages and all CNP recipients; separate wall solver budget from measured CPU.
7. Quality: exhaustive tiny checks validate the objective. Realistic scale needs
   the budget study and honest failure counts; a bounded heuristic is not optimum.
8. Limitations: snapshot predictions, open routes, accumulated load/no reload,
   conservative rounding, custom-rule postfilter, no certified realistic optimum.

Human tasks still pending: R5 counting agreement, R3 callback against their branch,
buddy PR review, teach-back and unscripted viva. These cannot be completed by a
code-generation session on the student's behalf.
