"""Build a deterministic multi-vehicle demo config for the replay (R2, Week 4).

Run from the repo root:
    python -m src.viz.demo_scenario --vehicles 10 --orders 30 --seed 7

Writes configs/viz_demo.yaml. Each vehicle's route is depot -> its orders -> depot,
built from our own A* (free-flow cost) leg by leg, so every order node lies on a
route and run.py's assign_orders hands every order to a vehicle that visits it.
"""
import argparse
import math
from pathlib import Path

import numpy as np
import yaml

from src.search.astar import astar
from src.search.heuristics import make_heuristic

OUT_FILE = Path("configs") / "viz_demo.yaml"
TW_START, TW_END = 21600.0, 36000.0
DURATION_S = 14400.0
CAPACITY = 100.0


def _dist(G, a, b):
    """Rough planar distance in degrees (only used to rank nodes, not as a cost)."""
    na, nb = G.nodes[a], G.nodes[b]
    dlon = (na["lon"] - nb["lon"]) * math.cos(math.radians(na["lat"]))
    return math.hypot(na["lat"] - nb["lat"], dlon)


def concat_route(G, stops, heuristic):
    """A* leg by leg through `stops`; the shared junction node is kept once."""
    route = [stops[0]]
    for a, b in zip(stops, stops[1:]):
        if a == b:
            continue
        leg = astar(G, a, b, heuristic=heuristic).path
        if not leg:
            raise RuntimeError(f"no path {a} -> {b}")
        route += leg[1:]                    # leg[0] == route[-1]: drop the duplicate
    return route


def assign_to_vehicles(G, vehicles, order_nodes):
    """Balanced nearest-depot assignment, then nearest-neighbour visiting order."""
    per_vehicle = math.ceil(len(order_nodes) / len(vehicles))
    plan = {v["id"]: [] for v in vehicles}
    # Orders closest to some depot are placed first so they get their best vehicle.
    ranked = sorted(range(len(order_nodes)),
                    key=lambda i: min(_dist(G, order_nodes[i], v["depot_node"]) for v in vehicles))
    for i in ranked:
        node = order_nodes[i]
        free = [v for v in vehicles if len(plan[v["id"]]) < per_vehicle]
        best = min(free, key=lambda v: (_dist(G, node, v["depot_node"]) * (1 + 0.3 * len(
            plan[v["id"]])), v["id"]))
        plan[best["id"]].append(i)
    for v in vehicles:                        # visit order: nearest neighbour from depot
        todo, here, seq = list(plan[v["id"]]), v["depot_node"], []
        while todo:
            nxt = min(todo, key=lambda i: (_dist(G, here, order_nodes[i]), i))
            seq.append(nxt)
            todo.remove(nxt)
            here = order_nodes[nxt]
        plan[v["id"]] = seq
    return plan


def build_config(G, n_vehicles=10, n_orders=30, seed=7):
    rng = np.random.default_rng(seed)
    nodes = sorted(G.nodes)
    n_depots = int(rng.integers(2, 4))        # 2 or 3 depots
    picks = rng.choice(len(nodes), size=n_depots + n_orders, replace=False)
    depots = [int(nodes[i]) for i in picks[:n_depots]]
    order_nodes = [int(nodes[i]) for i in picks[n_depots:]]

    orders = []
    for i, node in enumerate(order_nodes, start=1):
        orders.append({
            "id": f"O{i}", "node": node,
            "demand": float(rng.integers(5, 16)),
            "priority": int(rng.integers(1, 4)),
            "release_time": 0.0,
            "service_time": 300.0,
            "tw_start": TW_START, "tw_end": TW_END,
        })

    vehicles = [{"id": f"V{k}", "depot_node": depots[(k - 1) % n_depots],
                 "current_node": depots[(k - 1) % n_depots], "capacity": CAPACITY}
                for k in range(1, n_vehicles + 1)]
    plan = assign_to_vehicles(G, vehicles, order_nodes)
    h = make_heuristic(G)
    for v in vehicles:
        stops = [v["depot_node"]] + [order_nodes[i] for i in plan[v["id"]]] + [v["depot_node"]]
        v["route"] = concat_route(G, stops, h)

    return {
        "run_id": "viz_demo",
        "scenario": "viz_demo",
        "mode": "independent",
        "seed": seed,
        "headless": True,
        "start_time_s": TW_START,
        "duration_seconds": DURATION_S,
        "disruption_rate_per_hour": 10.0,
        "disruptions": {"min_duration_s": 600.0, "max_duration_s": 1800.0,
                        "min_spike": 1.2, "max_spike": 3.0, "max_closure_attempts": 20},
        "log_path": "logs/viz_demo.jsonl",
        "vehicles": vehicles,
        "orders": orders,
    }


def check_assignment(config):
    """Every order goes to a vehicle whose route visits its node (no fallback)."""
    from src.sim.run import assign_orders, build_order, build_vehicle
    vehicles = [build_vehicle(v) for v in config["vehicles"]]
    orders = [build_order(o) for o in config["orders"]]
    assignment = assign_orders(vehicles, orders)
    by_id = {v.id: v for v in vehicles}
    bad = [o.id for vid, os_ in assignment.items() for o in os_
           if o.node != by_id[vid].current_node and o.node not in by_id[vid].remaining_route]
    return assignment, bad


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write the replay demo config.")
    parser.add_argument("--vehicles", type=int, default=10)
    parser.add_argument("--orders", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default=str(OUT_FILE))
    args = parser.parse_args(argv)

    from src.world.graph_loader import load_road_graph
    G = load_road_graph("secunderabad")
    config = build_config(G, args.vehicles, args.orders, args.seed)
    assignment, bad = check_assignment(config)
    if bad:
        raise SystemExit(f"orders not on their vehicle's route: {bad}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (f"# Generated by: python -m src.viz.demo_scenario --vehicles {args.vehicles} "
              f"--orders {args.orders} --seed {args.seed}\n# Do not edit by hand.\n")
    out.write_text(header + yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    depots = sorted({v["depot_node"] for v in config["vehicles"]})
    print(f"wrote {out}: {len(config['vehicles'])} vehicles, {len(config['orders'])} orders, "
          f"{len(depots)} depots {depots}")
    for v in config["vehicles"]:
        print(f"  {v['id']}: route {len(v['route'])} nodes, "
              f"orders {[o.id for o in assignment[v['id']]]}")


if __name__ == "__main__":
    main()
