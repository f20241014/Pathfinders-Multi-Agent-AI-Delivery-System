import argparse
import yaml
from src.sim.world import World
from src.sim.models import Vehicle, Order
from src.sim.environment import DeliverySimEnvironment


def main():
    parser = argparse.ArgumentParser(
        description="Run headless delivery simulation."
    )
    parser.add_argument(
        "--config",
        default="configs/sim_default.yaml",
        help="Path to config",
    )
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    map_path = config.get(
        "map_path", "data/processed/secunderabad.graphml"
    )
    world = World.from_defaults(map_path)

    env = DeliverySimEnvironment(world, config)

    # TODO(R4/R5): Planner and vehicle order allocation will
    # assign subset of orders to vehicles
    v1 = Vehicle(
        id="V1",
        depot_node=1,
        capacity=100.0,
        current_node=1,
        remaining_route=[2],
    )
    o1 = Order(
        id="O1",
        node=2,
        demand=20.0,
        priority=1,
        tw_start=21600.0,
        tw_end=43200.0,
        service_time=60.0,
    )

    env.add_vehicle(v1, [o1])
    duration = config.get("duration_seconds", 3600.0)
    env.run(duration)

    log_path = config.get("log_path", "logs/sim.jsonl")
    print(f"Simulation completed. Log saved to: {log_path}")


if __name__ == "__main__":
    main()
