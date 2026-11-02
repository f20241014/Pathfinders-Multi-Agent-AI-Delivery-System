# Simulation Log Schema

Log files are written line-by-line to `logs/<run_id>.jsonl`. Note: this schema must be confirmed with R8.

## Column Order & Data Types
Each line is a JSON object containing the following primary keys:

1. `t` (float): Absolute simulation timestamp in seconds from midnight ($\text{start\_time\_s} + \text{env.now}$, where default $\text{start\_time\_s} = 21600.0$, representing 06:00 AM).
2. `event_type` (str): Name of the logged simulation event.
3. `payload` (dict): Event-specific key-value details.

## Core Event Types & Payloads

- `sim_start`: `{}`
- `edge_enter`: `{"vehicle_id": str, "edge": [u, v, key], "expected_duration": float}`
- `edge_exit`: `{"vehicle_id": str, "node": int}`
- `order_delivered`: `{"vehicle_id": str, "order_id": str}`
- `blocked_wait`: `{"vehicle_id": str, "edge": [u, v, key]}`
- `capacity_blocked`: `{"vehicle_id": str, "order_id": str, "demand": float, "capacity": float}`
- `disruption`: `{"edge": [u, v, key], "expiry": float}`
- `order_failed`: `{"order_id": str, "reason": str}`
- `sim_complete`: `{}`