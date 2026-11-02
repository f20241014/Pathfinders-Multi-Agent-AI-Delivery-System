# Simulation Core (R1, `src/sim`)

Discrete-event simulator (SimPy) for the delivery fleet on R2's real Secunderabad road graph.

## Running

```bash
python -m src.sim.run --config configs/sim_default.yaml
```

Writes `logs/<run_id>.jsonl` (schema: `docs/log_schema.md`). Without R6's data/torch you
will see `Traffic model unavailable, using free-flow times` - this is expected.

## Files

| file | what it does |
|------|--------------|
| `world.py` | `World`: road graph, travel times, closures, spikes, R6 traffic model hook. `FakeWorld` for tests. |
| `events.py` | `EventGenerator`: D11 Poisson disruptions (spikes, closures, new orders). |
| `environment.py` | `DeliverySimEnvironment`: vehicles drive routes, serve orders, log events. |
| `models.py` | `Order`, `Vehicle`, `Event` dataclasses. |
| `logger.py` | `SimulationLogger`: 9-key JSONL lines. |
| `interfaces.py` | Abstract `Planner`, `Predictor`, `Trigger`, `Negotiator`, `MetricsLogger`, and `Route`. |
| `run.py` | Builds world/vehicles/orders from a YAML config and runs it. |
| `scenarios.py` | `make_demo_config(world)` random demo config. |

## Clock

Every time is **absolute seconds from midnight**: `t = start_time_s + env.now`.
Default `start_time_s = 21600` (06:00); default run length 14400 s (until 10:00, D4).
Order time windows, release times, closure/spike start and expiry all use this clock.

## Travel time

```
edge_time(u, v, key, t) = inf                                   if the road is closed at t
                        = free_flow x traffic_mult x spike_mult  otherwise
```

- `free_flow`: edge attribute `free_flow_time` from R2's `load_road_graph`
  (fallbacks: `length / speed`, `weight / speed`, 100 m / speed with one warning).
- `traffic_mult`: R6 `TrafficModel.actual_multiplier_uv(str(u), str(v), t)`; 1.0 if the
  model is missing or the edge is unknown.
- `spike_mult`: product of all active spikes on the edge.
- A closure / spike is active for `start <= t < expiry`.
- `edge_key(u, v)` picks the fastest parallel road (5 real roads have key 1).
- The travel time is fixed when the vehicle **enters** an edge.
- `predicted_time(u, v, t, horizon_min)` uses R6's `Predictor`, else free-flow.
- `cost_fn_at(t)` gives a `cost_fn(u, v, data)` for R2's `astar` / `dijkstra`.

## Vehicles and orders

- A vehicle first serves orders at its start node, then drives `remaining_route`
  (a route that repeats the current node is fine).
- Closed road: the vehicle logs `blocked_wait` and re-checks every 60 s.
- At each node, for each pending order there:
  1. now > `tw_end` -> `order_failed` (`time_window_missed`)
  2. `max(tw_start, release_time) > tw_end` -> `order_failed` (`invalid_time_window`)
  3. `load + demand > capacity` -> `capacity_blocked`, order deferred
  4. else wait until `max(tw_start, release_time)`, serve for `service_time`,
     log `order_delivered`, `load += demand`.
- At the end of the route, leftovers fail with `capacity_exceeded_unservable`
  (deferred) or `not_on_route`. Load never decreases yet, so a deferred order cannot
  succeed later.

## Disruptions (D11)

Poisson arrivals at `disruption_rate_per_hour` (mean gap 3600 / rate s). Each event is
a traffic spike (40%, x1.2-3.0), a closure (30%) or a new order (30%). Spikes and
closures hit a random road for 600-1800 s starting at the event time. Events are
logged and passed to every `env.subscribe(callback)` listener.

## Hand-offs

- **R3 (orders)**: `env.add_order(order)`; `new_order` events only announce `dyn_N`
  for now (`TODO(R3)` in `events.py`). `Vehicle.current_load` is available for rules.
- **R4/R5 (planning, negotiation)**: replace `assign_orders` in `run.py`
  (`TODO(R4/R5)`); `Route(nodes, expected_times, order_ids)`; depot unloading.
- **R6 (traffic)**: `World.from_defaults` loads `TrafficModel` + `Predictor` when
  available; `TODO(R6)` in `world.py` to confirm the clock convention.
- **R7 (triggers / re-routing)**: subscribe to `disruption` events; vehicles currently
  wait at closures (`TODO(R7)`); use `world.cost_fn_at(t)` to re-plan.
- **R8 (metrics)**: read the JSONL log, schema in `docs/log_schema.md`.

Not done yet: closure-connectivity guard (D11 "closures never disconnect pending
destinations") is Week 3.
