# Simulation Core (r1/sim-core)

This module provides the discrete-event simulation engine built on SimPy for the Pathfinders Multi-Agent AI Delivery System.

## Architectural Notes & Handoffs

- **Clock Convention**: All logged timestamps (`t`) represent absolute simulation time in seconds from midnight ($t = \text{start\_time\_s} + \text{env.now}$). Default `start_time_s` is `21600.0` (06:00:00 AM).
- **Execution Modes**: The `mode` setting in configuration (`independent`, `centralized`, `full`) acts as a label until R4/R5 planning & negotiation modules are integrated.
- **Dynamic Orders (R3 Handoff)**: External order generators inject orders into the environment using `env.add_order(order)`. Event dispatching for `new_order` is marked as `TODO(R3)`.
- **Order Allocation (R4/R5 Handoff)**: Multi-vehicle route planning and order-to-vehicle allocation are pending implementation by R4/R5.

## Running the Simulation

```bash
python -m src.sim.run --config configs/sim_default.yaml
