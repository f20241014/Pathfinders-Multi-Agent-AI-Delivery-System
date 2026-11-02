# Project Architecture Decisions

Defaults taken from the project plan; change a line here if the team decides otherwise.

* **D1 Map region and size:** Secunderabad, 2,377 nodes; 6,077 raw edges, 6,056 after keeping the fastest parallel edge.
* **D2 Fleet and depots:** 10-20 vehicles, 2-3 depots, identical vehicles first, capacity in abstract units.
* **D3 Orders:** 100-300 per scenario, 3 priority tiers, time windows from Amazon distributions, dynamic order arrivals.
* **D4 Simulated period:** 4-hour window covering morning peak (06:00 to 10:00 AM); headless execution at >=200x real-time speed.
* **D5 Definition of a conflict:** Fleet-slot capacity per road class (Residential: 1, Secondary: 2, Primary: 3). Conflict = predicted concurrent vehicles above capacity.
* **D6 Tau and Delta-T:** Delta-t = arrival time gap triggering resource clash; Tau = time horizon justifying active negotiation.
* **D7 Message counting:** Point-to-point message = 1 count; broadcast to m agents = m count.
* **D8 New-order allocation:** Contract-net protocol for decentralized execution; re-optimization for centralized mode.
* **D9 CPU time:** Evaluated using `time.process_time()` across replanning cycles on single thread.
* **D10 Agent Information:** Shared real-time road-status feed (closures and spikes) plus predicted weights.
* **D11 Disruption process:** Poisson arrivals (lambda in {0, 2, 5, 10, 20} / hr); 40% traffic spikes, 30% closures, 30% new orders. Closures never disconnect pending destinations.
* **D12 Metric definitions:** Evaluated as defined in Section 7 of the project specification.
* **Traversal Policy:** Traversal time is fixed when a vehicle enters an edge (mid-edge disruptions affect subsequent edge entries).
* **Clock Alignment:** Standardized all simulation event logging and disruption checking to use absolute time in seconds from midnight ($t = \text{start\_time\_s} + \text{env.now}$).
* **Closure Connectivity Guard:** Deferred to Week 3 (TODO(R1)).
* **Travel Time:** edge time = R2 `free_flow_time` x R6 traffic multiplier x active spike multipliers; infinite while the road is closed (closures/spikes active for start <= t < expiry). Free-flow only when R6's model is unavailable.
* **Time Windows:** Absolute seconds from midnight. A vehicle arriving early waits until max(tw_start, release_time); arriving after tw_end fails the order (`time_window_missed`); service takes `service_time`.