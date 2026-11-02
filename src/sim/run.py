"""Headless run: python -m src.sim.run --config configs/sim_default.yaml"""
import argparse
import logging
from typing import Any, Dict, List

import yaml

from src.sim.environment import DEFAULT_DURATION_S, DeliverySimEnvironment
from src.sim.models import Order, Vehicle
from src.sim.world import DEFAULT_MAP_PATH, World


def build_vehicle(cfg: Dict[str, Any]) -> Vehicle:
    route = [int(n) for n in cfg.get("route", [])]
    depot = int(cfg["depot_node"])
    return Vehicle(
        id=str(cfg["id"]),
        depot_node=depot,
        capacity=float(cfg["capacity"]),
        current_node=int(cfg.get("current_node", depot)),
        remaining_route=route,
        load=float(cfg.get("load", 0.0)),
        allowed_road_classes=cfg.get("allowed_road_classes"),
    )


def build_order(cfg: Dict[str, Any]) -> Order:
    return Order(**cfg)   # unknown keys raise TypeError: nothing is silently ignored


def assign_orders(vehicles: List[Vehicle], orders: List[Order]) -> Dict[str, List[Order]]:
    """Give each order to the first vehicle whose route visits its node.

    TODO(R4/R5): replace with the real planner / allocation.
    An order no route visits goes to the first vehicle, which logs it as
    order_failed "not_on_route" at the end of its route.
    """
    assignment: Dict[str, List[Order]] = {v.id: [] for v in vehicles}
    for order in orders:
        for vehicle in vehicles:
            if order.node == vehicle.current_node or order.node in vehicle.remaining_route:
                assignment[vehicle.id].append(order)
                break
        else:
            if vehicles:
                assignment[vehicles[0].id].append(order)
    return assignment


def run_from_config(config: Dict[str, Any]) -> str:
    """Build the world, vehicles and orders from a config and run. Returns the log path."""
    map_path = config.get("map_path", DEFAULT_MAP_PATH)
    world = World.from_defaults(map_path, seed=int(config.get("seed", 42)))
    env = DeliverySimEnvironment(world, config)

    vehicles = [build_vehicle(v) for v in config.get("vehicles", [])]
    orders = [build_order(o) for o in config.get("orders", [])]
    for order in orders:
        env.add_order(order)
    assignment = assign_orders(vehicles, orders)
    for vehicle in vehicles:
        env.add_vehicle(vehicle, assignment[vehicle.id])

    env.run(float(config.get("duration_seconds", DEFAULT_DURATION_S)))
    return env.log_path


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Run headless delivery simulation.")
    parser.add_argument("--config", default="configs/sim_default.yaml", help="Path to config")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    log_path = run_from_config(config)
    print(f"Simulation completed. Log saved to: {log_path}")


if __name__ == "__main__":
    main()
