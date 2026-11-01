#### File 3: `docs/log_schema.md`
```markdown
# Simulation Log Schema (`docs/log_schema.md`)

Log files are written line-by-line to `logs/<run_id>.jsonl`. Note: this schema must be confirmed with R8.

## Column Order & Data Types
Each row is a JSON object with the exact keys:

1. `run_id` (str): Identifier for the simulation run.
2. `mode` (str): Simulation mode (`independent`, `centralized`, `full`).
3. `seed` (int): Random seed used.
4. `scenario` (str): Scenario name.
5. `rate` (float): Disruption rate per simulated hour.
6. `t` (float): Simulation timestamp in seconds.
7. `agent_id` (str): Vehicle ID or `"env"`.
8. `event` (str): Name of the logged event.
9. `payload` (dict): Dictionary with event-specific parameters.

## Event Types & Payloads
- `sim_start`: `{}`
- `edge_enter`: `{"edge": [u, v], "cost": float}`
- `edge_exit`: `{"node": int}`
- `stop_served`: `{"order_id": str, "load": float}`
- `blocked_wait`: `{"edge": [u, v]}`
- `capacity_blocked`: `{"order_id": str, "demand": float}`
- `disruption`: `{"type": str, "target": str, "magnitude": float, "duration": float}`
- `order_failed`: `{"order_id": str}`
- `sim_complete`: `{}`