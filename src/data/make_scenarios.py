"""
R3 · Week 3: build the scenario set (small / medium / large x uniform / clustered / hotspot).

    python -m src.data.make_scenarios --profile-dir data/profile --seeds 0
    python -m src.data.make_scenarios --placeholder-profile --seeds 0     # pipeline dry run only

Writes configs/scenarios/<size>_<layout>_s<seed>.yaml in R1's config format, so each file runs
directly with:  python -m src.sim.run --config configs/scenarios/medium_clustered_s0.yaml

    size     vehicles  depots  orders   (D2, D3 in DECISIONS.md)
    small       10        2      100
    medium      15        3      200
    large       20        3      300

Orders come straight from src/data/orders_from_amazon.py in R1's units: seconds since midnight
inside 06:00-10:00 (D4), and R1's defaults tw_start 0.0 / tw_end 86400.0 for "no time window".

Assumptions to state in the report: homogeneous fleet; capacity set so total demand is
LOAD_FACTOR of total fleet capacity; depots = graph nodes nearest to k-means centres of the map.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.data.orders_from_amazon import Empirical, generate, kmeans
from src.kr.ontology import SIM_END_S, SIM_START_S, tw_of

SIZES = {"small": (10, 2, 100), "medium": (15, 3, 200), "large": (20, 3, 300)}
LAYOUTS = ("uniform", "clustered", "hotspot")
START_S = SIM_START_S
HORIZON_S = SIM_END_S - SIM_START_S
LOAD_FACTOR = 0.8


class PlaceholderProfile:
    """Stand-in distributions so the pipeline can run before the Amazon data is downloaded.

    NOT real data. Scenario files built from it carry source: PLACEHOLDER and must be regenerated
    from data/profile before any experiment.
    """

    def __init__(self, seed=0):
        rng = np.random.default_rng(seed)
        self.packages_per_stop = rng.choice([1, 1, 1, 2, 2, 3], size=5000).tolist()
        self.service_s = rng.gamma(2.0, 60.0, size=5000).tolist()
        self.volume = rng.lognormal(8.5, 0.9, size=5000).tolist()
        self.unit_cm3 = float(np.median(self.volume))
        self.p_tw = 0.1
        self.tw_width_h = rng.uniform(1.0, 4.0, size=500).tolist()
        self.tw_offset_h = rng.uniform(0.0, 8.0, size=500).tolist()


def load_nodes(graph_name: str):
    from src.world.graph_loader import load_road_graph

    G = load_road_graph(graph_name)
    nodes = pd.DataFrame(
        [(n, d["x"], d["y"]) for n, d in G.nodes(data=True)], columns=["node", "x", "y"]
    )
    return G, nodes


def pick_depots(nodes: pd.DataFrame, k: int, seed: int) -> list[int]:
    X = nodes[["x", "y"]].to_numpy(float)
    lab = kmeans(X, k, seed)
    depots = []
    for j in range(k):
        members = np.flatnonzero(lab == j)
        centre = X[members].mean(0)
        depots.append(
            int(nodes["node"].to_numpy()[members[np.argmin(((X[members] - centre) ** 2).sum(1))]])
        )
    return depots


def build_config(
    emp, G, nodes, size: str, layout: str, seed: int, source: str, map_path: str
) -> dict:
    n_veh, n_dep, n_ord = SIZES[size]
    depots = pick_depots(nodes, n_dep, 10_000 + seed)
    orders = generate(emp, nodes, n_ord, seed, layout, depot_nodes=tuple(depots))
    total = sum(o.demand for o in orders)
    capacity = float(math.ceil(total / (n_veh * LOAD_FACTOR)))

    order_cfgs = [asdict(o) for o in orders]
    vehicles = [
        dict(
            id=f"V{i + 1:02d}",
            depot_node=depots[i % n_dep],
            current_node=depots[i % n_dep],
            capacity=capacity,
            route=[],
        )
        for i in range(n_veh)
    ]
    name = f"{size}_{layout}"
    return {
        "run_id": f"{name}_s{seed}",
        "scenario": name,
        "seed": seed,
        "mode": "independent",  # the experiment runner overrides mode and rate
        "map_path": map_path,
        "start_time_s": START_S,
        "duration_seconds": HORIZON_S,
        "disruption_rate_per_hour": 0.0,
        "headless": True,
        "vehicles": vehicles,
        "orders": order_cfgs,
        "scenario_meta": {
            "generator": "src/data/make_scenarios.py (R3)",
            "demand_source": source,
            "layout": layout,
            "depots": depots,
            "unit_cm3": round(float(emp.unit_cm3), 1),
            "load_factor": LOAD_FACTOR,
            "dynamic_orders": int(sum(o.release_time > START_S for o in orders)),
            "orders_with_tw_from_data": int(sum(tw_of(o) is not None for o in orders)),
            "priority_counts": {p: int(sum(o.priority == p for o in orders)) for p in (1, 2, 3)},
        },
    }


def check_servable(G, cfg) -> list[str]:
    """Orders that no vehicle could serve even alone (free-flow times from R2's matrix)."""
    from src.kr.adapters import travel_time_from_matrix
    from src.kr.csp import eligible_vehicles
    from src.search.dijkstra import free_flow_cost
    from src.search.travel_matrix import TravelTimeMatrix
    from src.sim.run import build_order, build_vehicle

    vehicles = [build_vehicle(v) for v in cfg["vehicles"]]
    orders = [build_order(o) for o in cfg["orders"]]
    nodes = {o.node for o in orders} | {v.depot_node for v in vehicles}
    tt = travel_time_from_matrix(TravelTimeMatrix(G, lambda t: free_flow_cost), nodes, bucket_s=1e9)
    return [
        o.id
        for o in orders
        if not eligible_vehicles(o, vehicles, tt, t_now=o.release_time, check_release=False)[0]
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile-dir", default="data/profile")
    ap.add_argument(
        "--placeholder-profile",
        action="store_true",
        help="use stand-in distributions (dry run only, never for experiments)",
    )
    ap.add_argument("--graph", default="secunderabad")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--sizes", nargs="+", default=list(SIZES))
    ap.add_argument("--out-dir", default="configs/scenarios")
    ap.add_argument("--skip-check", action="store_true")
    a = ap.parse_args()

    if a.placeholder_profile:
        emp, source = (
            PlaceholderProfile(),
            "PLACEHOLDER (not real data, regenerate from data/profile)",
        )
    else:
        if not (Path(a.profile_dir) / "packages.csv").exists():
            raise SystemExit(
                f"{a.profile_dir}/packages.csv not found: run src/data/profile_amazon.py first, "
                "or pass --placeholder-profile for a dry run"
            )
        emp, source = Empirical(a.profile_dir), "Amazon Last Mile 2021 statistics (CC BY-NC 4.0)"

    G, nodes = load_nodes(a.graph)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for seed in a.seeds:
        for size in a.sizes:
            for layout in LAYOUTS:
                cfg = build_config(
                    emp, G, nodes, size, layout, seed, source, f"data/processed/{a.graph}.graphml"
                )
                if not a.skip_check:
                    bad = check_servable(G, cfg)
                    cfg["scenario_meta"]["orders_unservable_alone"] = bad
                path = out / f"{size}_{layout}_s{seed}.yaml"
                with open(path, "w") as f:
                    yaml.safe_dump(cfg, f, sort_keys=False)
                m = cfg["scenario_meta"]
                print(
                    f"{path}: {len(cfg['orders'])} orders, {len(cfg['vehicles'])} vehicles, "
                    f"capacity {cfg['vehicles'][0]['capacity']:.0f}, "
                    f"dynamic {m['dynamic_orders']}, priorities {m['priority_counts']}, "
                    f"unservable {len(m.get('orders_unservable_alone', []))}"
                )


if __name__ == "__main__":
    main()