# R4 catch-up record

Work is recorded at actual implementation time (November 2026). Week labels
refer to the execution plan, not historical evidence of participation.

- W1: shared feasibility/cost conventions, hand-checkable two-vehicle CVRP,
  isolated dependency file, primary-source implementation notes and tests.

- W2: feasible marginal insertion, deterministic CNP, individual recipient logging, duplicate-award guard and four behavioral tests.

- W3: OR-Tools CVRPTW, residual-load/availability partial state, priorities, explicit drops, conservative integer scaling and 2N message accounting; four solver tests.

- W4: shared forecast/incident graph adapter, road profiles, cached paths, mode/event controller, mid-edge/active-service snapshots and explicit failure logs; integration boundary tested.

- W5: opt-in executable SimPy allocation harness; dynamic arrivals/closure during travel; exact-once outcomes and baseline-vs-exhaustive quality tests.
