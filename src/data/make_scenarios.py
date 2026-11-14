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

Assumptions to state in the report: homogeneous fleet by default (D2); capacity set so total
demand is LOAD_FACTOR of total fleet capacity; depots = graph nodes nearest to k-means centres.

Week 4 (final configs): --large-share 0.3 makes 30% of each fleet large vehicles (KR-3: no
residential / living_street / service / unclassified roads, written as R1's allowed_road_classes).
On the Secunderabad map a large vehicle can reach only about 28% of the nodes, so with large
vehicles the depots move onto the large-vehicle road network, and the "servable" check applies
the road rules (an order only large vehicles could reach would be flagged).
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


def large_network(G) -> set:
    """Nodes in the largest strongly connected part of the map a large vehicle may drive (KR-3)."""
    import networkx as nx

    from src.kr.planner_rules import LARGE_VEHICLE_CLASSES, RoadRules
    from src.sim.models import Vehicle

    probe = Vehicle("probe", 0, 1.0, 0, allowed_road_classes=LARGE_VEHICLE_CLASSES)
    bad = RoadRules(G).class_blocked(probe)
    H = nx.DiGraph([(u, v) for u, v in set(G.edges()) if (u, v) not in bad])
    return max(nx.strongly_connected_components(H), key=len) if H.number_of_nodes() else set()


def pick_depots(nodes: pd.DataFrame, k: int, seed: int, allowed=None) -> list[int]:
    """Node nearest each k-means centre; with allowed, only nodes in that set can be depots."""
    if allowed is not None:
        nodes = nodes[nodes["node"].isin(allowed)].reset_index(drop=True)
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
    emp,
    G,
    nodes,
    size: str,
    layout: str,
    seed: int,
    source: str,
    map_path: str,
    large_share: float = 0.0,
    large_nodes=None,
) -> dict:
    from src.kr.planner_rules import LARGE_VEHICLE_CLASSES

    n_veh, n_dep, n_ord = SIZES[size]
    n_large = int(round(large_share * n_veh))
    if n_large and large_nodes is None:
        large_nodes = large_network(G)
    depots = pick_depots(nodes, n_dep, 10_000 + seed, large_nodes if n_large else None)
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
    first_large = n_veh - n_large  # the last n_large vehicles are large (KR-3)
    for v in vehicles[first_large:]:
        v["allowed_road_classes"] = list(LARGE_VEHICLE_CLASSES)
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
            "large_vehicles": n_large,
            "dynamic_orders": int(sum(o.release_time > START_S for o in orders)),
            "orders_with_tw_from_data": int(sum(tw_of(o) is not None for o in orders)),
            "priority_counts": {p: int(sum(o.priority == p for o in orders)) for p in (1, 2, 3)},
        },
    }


def check_servable(G, cfg) -> list[str]:
    """Orders that no vehicle could serve even alone, at free-flow speed, under the road rules.

    Vehicles with the same allowed road classes share one rule-aware travel-time matrix (R2's).
    """
    from src.kr.adapters import travel_time_from_matrix
    from src.kr.csp import eligible_vehicles
    from src.kr.planner_rules import RoadRules
    from src.search.travel_matrix import TravelTimeMatrix
    from src.sim.run import build_order, build_vehicle

    vehicles = [build_vehicle(v) for v in cfg["vehicles"]]
    orders = [build_order(o) for o in cfg["orders"]]
    nodes = {o.node for o in orders} | {v.depot_node for v in vehicles}
    rules = RoadRules(G)
    groups: dict = {}
    for v in vehicles:
        groups.setdefault(tuple(sorted(v.allowed_road_classes or [])), []).append(v)
    servable = set()
    for group in groups.values():
        ttm = TravelTimeMatrix(G, rules.cost_fn_factory(group[0]))
        tt = travel_time_from_matrix(ttm, nodes, bucket_s=1e9)
        for o in orders:
            if (
                o.id not in servable
                and eligible_vehicles(o, group, tt, t_now=o.release_time, check_release=False)[0]
            ):
                servable.add(o.id)
    return [o.id for o in orders if o.id not in servable]


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
    ap.add_argument(
        "--large-share",
        type=float,
        default=0.0,
        help="share of each fleet that are large vehicles (KR-3); default 0 (D2)",
    )
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
    large_nodes = large_network(G) if a.large_share > 0 else None
    for seed in a.seeds:
        for size in a.sizes:
            for layout in LAYOUTS:
                cfg = build_config(
                    emp,
                    G,
                    nodes,
                    size,
                    layout,
                    seed,
                    source,
                    f"data/processed/{a.graph}.graphml",
                    a.large_share,
                    large_nodes,
                )
                if not a.skip_check:
                    bad = check_servable(G, cfg)
                    cfg["scenario_meta"]["orders_unservable_alone"] = bad
                suffix = f"_large{int(round(a.large_share * 100))}" if a.large_share > 0 else ""
                path = out / f"{size}_{layout}{suffix}_s{seed}.yaml"
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
