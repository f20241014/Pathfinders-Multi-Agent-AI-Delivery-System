"""
R3 · Order generator v1: realistic orders on OUR map from Amazon demand STATISTICS.

Amazon coordinates are obfuscated, so no geography is used from them. We sample from the empirical
distributions written by src/data/profile_amazon.py and place orders on graph nodes of R2's map.

    python src/data/orders_from_amazon.py --profile-dir data/profile --nodes data/map/nodes.csv \
        --n-orders 200 --layout clustered --seed 0 --out configs/scenarios/medium_clustered_s0.json

nodes.csv needs columns: node, x, y  (R2 can export it from the OSMnx graph: ox.graph_to_gdfs(G, edges=False)).

What comes from the data vs. what is our assumption (put this table in the report):
    data:        packages per stop, package volume, has-time-window share, window width,
                 window start offset, service time per stop
    assumption:  priority split (express/standard/economy), share of dynamic orders,
                 demand zones on the map (k-means), unit size (1 unit = median package volume)
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.kr.ontology import Order  # noqa: E402

LAYOUTS = ("uniform", "clustered", "hotspot")


class Empirical:
    """The distributions we sample from, loaded from the profile CSVs."""

    def __init__(self, profile_dir: str | Path):
        d = Path(profile_dir)
        stops = pd.read_csv(d / "packages_per_stop.csv")
        pk = pd.read_csv(d / "packages.csv")
        self.packages_per_stop = stops["n_packages"].clip(lower=1).to_numpy()
        self.service_s = stops["service_sum_s"].clip(lower=0).to_numpy()
        self.volume = pk["volume_cm3"][pk["volume_cm3"] > 0].to_numpy()
        self.unit_cm3 = float(np.median(self.volume))
        # time windows at stop level: a stop has a window if any of its packages has one
        tw = pk[pk["has_tw"] == True]  # noqa: E712
        self.p_tw = float(pk.groupby(["route_id", "stop_id"])["has_tw"].any().mean())
        self.tw_width_h = tw["tw_width_h"].dropna().to_numpy()
        self.tw_offset_h = tw["tw_start_after_dep_h"].dropna().to_numpy()


def kmeans(X: np.ndarray, k: int, rng: np.random.Generator, iters: int = 50):
    """Plain k-means (Lloyd) over node coordinates -> demand zones."""
    C = X[rng.choice(len(X), size=k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((X[:, None, :] - C[None, :, :]) ** 2).sum(-1), axis=1)
        newC = np.array([X[lab == j].mean(0) if np.any(lab == j) else C[j] for j in range(k)])
        if np.allclose(newC, C):
            break
        C = newC
    return lab


def zone_weights(k: int, layout: str, rng: np.random.Generator) -> np.ndarray:
    if layout == "uniform":
        return np.ones(k) / k
    if layout == "clustered":            # a few busy zones, the rest quiet
        w = rng.dirichlet(np.full(k, 0.5))
        return w
    if layout == "hotspot":              # one zone takes ~50% of demand (e.g. a market area)
        w = np.ones(k)
        w[rng.integers(k)] = k - 1
        return w / w.sum()
    raise ValueError(f"layout must be one of {LAYOUTS}")


def generate(
    emp: Empirical,
    nodes: pd.DataFrame,
    n_orders: int,
    seed: int,
    layout: str = "uniform",
    horizon_s: float = 4 * 3600,          # D4
    depot_nodes: tuple = (),
    n_zones: int = 8,
    priority_split=(0.2, 0.5, 0.3),       # ASSUMPTION: express / standard / economy
    dynamic_share: float = 0.3,           # ASSUMPTION: share of orders released during the run (D3)
    min_tw_width_s: float = 30 * 60,
) -> list[Order]:
    rng = np.random.default_rng(seed)
    cand = nodes[~nodes["node"].isin(depot_nodes)].reset_index(drop=True)
    lab = kmeans(cand[["x", "y"]].to_numpy(float), n_zones, rng)
    w = zone_weights(n_zones, layout, rng)

    orders = []
    for i in range(n_orders):
        z = rng.choice(n_zones, p=w)
        node = int(cand["node"].to_numpy()[rng.choice(np.flatnonzero(lab == z))])

        n_pk = int(rng.choice(emp.packages_per_stop))
        vol = rng.choice(emp.volume, size=n_pk).sum()
        demand = max(1, math.ceil(vol / emp.unit_cm3))

        release = float(rng.uniform(0, 0.75 * horizon_s)) if rng.random() < dynamic_share else 0.0
        priority = int(rng.choice([1, 2, 3], p=priority_split))

        tw_start = tw_end = None
        if rng.random() < emp.p_tw and len(emp.tw_width_h):
            width = max(min_tw_width_s, float(rng.choice(emp.tw_width_h)) * 3600)
            offset = float(rng.choice(emp.tw_offset_h)) * 3600 if len(emp.tw_offset_h) else 0.0
            # Amazon windows are relative to a ~10 h route; rescale offsets into our horizon
            tw_start = release + max(0.0, offset) * (horizon_s / (10 * 3600))
            tw_start = min(tw_start, horizon_s - min_tw_width_s)
            tw_start = max(tw_start, release)           # window never opens before the order exists
            tw_end = min(tw_start + width, horizon_s)

        orders.append(
            Order(
                id=f"O{i:04d}",
                node=node,
                demand=demand,
                priority=priority,
                tw_start=tw_start,
                tw_end=tw_end,
                service_time=float(rng.choice(emp.service_s)),
                release_time=release,
            )
        )
    return orders


def compare_to_empirical(orders: list[Order], emp: Empirical) -> dict:
    """Definition of Done check: generated statistics match the empirical ones (two-sample KS test)."""
    from scipy.stats import ks_2samp

    out = {}
    svc = np.array([o.service_time for o in orders])
    out["service_time"] = ks_2samp(svc, emp.service_s).pvalue
    widths = np.array([(o.tw_end - o.tw_start) / 3600 for o in orders if o.has_tw])
    if len(widths) > 5:
        # widths are clipped to the horizon, so expect a lower p-value here; report it, don't hide it
        out["tw_width_h"] = ks_2samp(widths, emp.tw_width_h).pvalue
    out["share_with_tw_generated"] = float(np.mean([o.has_tw for o in orders]))
    out["share_with_tw_empirical"] = emp.p_tw
    return {k: round(float(v), 4) for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile-dir", default="data/profile")
    ap.add_argument("--nodes", required=True, help="CSV with node,x,y")
    ap.add_argument("--n-orders", type=int, default=200)
    ap.add_argument("--layout", choices=LAYOUTS, default="uniform")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--depots", type=int, nargs="*", default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    emp = Empirical(a.profile_dir)
    nodes = pd.read_csv(a.nodes)
    orders = generate(emp, nodes, a.n_orders, a.seed, a.layout, depot_nodes=tuple(a.depots))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "seed": a.seed, "layout": a.layout, "n_orders": a.n_orders,
        "unit_cm3": emp.unit_cm3, "source": "Amazon Last Mile 2021 statistics (CC BY-NC 4.0)",
    }
    json.dump({"meta": meta, "orders": [asdict(o) for o in orders]}, open(a.out, "w"), indent=1)
    print(f"wrote {len(orders)} orders to {a.out}")
    print("match vs empirical (KS p-values):", compare_to_empirical(orders, emp))


if __name__ == "__main__":
    main()