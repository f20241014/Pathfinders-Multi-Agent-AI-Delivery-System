# Simulation Log Schema

One JSON object per line, written to `logs/<run_id>.jsonl` (or `log_path` from the config).
Each run overwrites the old file. To be confirmed with R8 (metrics/plots).

## Keys (always all nine, in this order)

| # | key        | type         | meaning |
|---|------------|--------------|---------|
| 1 | `run_id`   | str          | from config `run_id` |
| 2 | `mode`     | str          | `independent` / `centralized` / `full` (label until R4/R5 land) |
| 3 | `seed`     | int          | RNG seed of the run |
| 4 | `scenario` | str          | from config `scenario` |
| 5 | `rate`     | float        | `disruption_rate_per_hour` (D11 lambda) |
| 6 | `t`        | float        | absolute seconds from midnight, `start_time_s + env.now`, rounded to 2 decimals (default start 21600 = 06:00) |
| 7 | `agent_id` | str          | vehicle id for vehicle events, `"env"` otherwise |
| 8 | `event`    | str          | event name (below) |
| 9 | `payload`  | object       | event details (below) |

Example:

```json
{"run_id": "sim_demo", "mode": "independent", "seed": 42, "scenario": "secunderabad_demo", "rate": 5.0, "t": 21600.0, "agent_id": "V1", "event": "edge_enter", "payload": {"edge": [12829715342, 5436549587, 0], "expected_duration": 9.05}}
```

## Events and payloads

Edges are `[u, v, key]` (OSM node ids, key of the road actually used).

| event | agent_id | payload |
|-------|----------|---------|
| `sim_start` | env | `{"start_time_s", "duration_seconds", "n_vehicles", "n_orders"}` |
| `edge_enter` | vehicle | `{"edge": [u, v, key], "expected_duration": float s}` (time fixed on entry) |
| `edge_exit` | vehicle | `{"node": int}` (node just reached) |
| `blocked_wait` | vehicle | `{"edge": [u, v, key]}` logged every 60 s while the next road is closed |
| `order_delivered` | vehicle | `{"order_id", "node", "demand"}`; `t` = end of service |
| `capacity_blocked` | vehicle | `{"order_id", "demand", "load", "capacity"}`; order is deferred |
| `order_failed` | vehicle | `{"order_id", "node", "reason"}` |
| `disruption` | env | `{"type": "traffic_spike" \| "closure", "edge": [u, v, key], "magnitude": float \| null, "duration": float s, "expiry": float t}`; `magnitude` is the spike multiplier, `null` for a closure |
| `new_order` | env | `{"order_id": "dyn_N", "release_time": float t}` |
| `sim_complete` | env | `{"delivered": int, "failed": int}` |

### `order_failed` reasons

| reason | when |
|--------|------|
| `time_window_missed` | vehicle arrives after `tw_end` |
| `invalid_time_window` | `max(tw_start, release_time) > tw_end` (can never be served) |
| `capacity_exceeded_unservable` | was `capacity_blocked` and still undelivered at the end of the route |
| `not_on_route` | the vehicle's route never reached the order's node |
