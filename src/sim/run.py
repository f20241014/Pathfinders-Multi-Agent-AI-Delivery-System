# src/sim/run.py
import argparse
import yaml
import logging
from src.sim.world import World
from src.sim.environment import DeliverySimEnvironment
from src.sim.models import Vehicle, Order

logging.basicConfig(level=logging.WARNING)

def main():
    parser = argparse.ArgumentParser(description="Run Delivery Simulation")
    parser.add_argument("--config", type=str, default="configs/sim_default.yaml")
    args = parser.parse_args()

    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    world = World.from_defaults(seed=config.get("seed", 42))
    env = DeliverySimEnvironment(world, config)

    orders = [Order(**o) for o in config.get("orders", [])]
    for v_cfg in config.get("vehicles", []):
        v = Vehicle(
            id=v_cfg["id"],
            depot_node=v_cfg["depot_node"],
            capacity=v_cfg["capacity"],
            current_node=v_cfg["current_node"],
            remaining_route=list(v_cfg["route"])
        )
        env.add_vehicle(v, orders)

    env.run(duration_seconds=config.get("duration_seconds", 14400.0))
    print(f"Simulation complete. Log written to logs/{config.get('run_id', 'default')}.jsonl")

if __name__ == "__main__":
    main()