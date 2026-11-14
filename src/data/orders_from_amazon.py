"""
R3 · Order generator: realistic orders on OUR map from Amazon demand STATISTICS.

Amazon coordinates are obfuscated, so no geography comes from them. We sample from the empirical
distributions written by src/data/profile_amazon.py and place orders on graph nodes of R2's map.

    python -m src.data.orders_from_amazon --profile-dir data/profile --nodes data/map/nodes.csv \
        --n-orders 200 --layout clustered --seed 0 --out configs/orders/medium_clustered_s0.json

nodes.csv needs columns node, x, y. Write it from R2's map with:
    python scripts/export_nodes.py

Orders are R1's src.sim.models.Order, in the units of docs/kr_ontology_rules.md: demand in capacity
units, all times in seconds since midnight inside 06:00-10:00. An order without a time window
gets R1's defaults tw_start = 0.0, tw_end = 86400.0 (never None, so R1's simulator can load it);
tw_of() reads exactly that pair as "no window".

What comes from the data vs our assumptions (put this table in the report):
    data        packages per stop, package volume, share of stops with a time window, window width,
                window start offset, service time per stop
    assumption  priority split 20/50/30 (express/standard/economy): the Amazon data has no
                priorities, so this is our choice (a minority of express orders, half standard);
                share of dynamic orders 30% (D3); demand zones = k-means on node coordinates;
                1 capacity unit = median package volume
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.kr.ontology import NO_TW_END, NO_TW_START, SIM_END_S, SIM_START_S, Order, tw_of

LAYOUTS = ("uniform", "clustered", "hotspot")
PRIORITY_SPLIT = (0.2, 0.5, 0.3)  # ASSUMPTION, see module docstring
DYNAMIC_SHARE = 0.3  # ASSUMPTION (D3: dynamic order arrivals)
AMAZON_ROUTE_H = 10.0  # Amazon window offsets are spread over a ~10 h route day


class Empirical:
    """The distributions we sample from, loaded from the profile CSVs."""

    def __init__(self, profile_dir: str | Path):
        d = Path(profile_dir)
        stops = pd.read_csv(d / "packages_per_stop.csv")
        pk = pd.read_csv(d / "packages.csv")
        self.packages_per_stop = stops["n_packages"].clip(lower=1).tolist()
        self.service_s = stops["service_sum_s"].clip(lower=0).tolist()
        self.volume = pk["volume_cm3"][pk["volume_cm3"] > 0].tolist()
        self.unit_cm3 = float(np.median(self.volume))
        tw = pk[pk["has_tw"].astype(bool)]
        self.p_tw = float(pk.groupby(["route_id", "stop_id"])["has_tw"].any().mean())
        self.tw_width_h = tw["tw_width_h"].dropna().tolist()
        self.tw_offset_h = tw["tw_start_after_dep_h"].dropna().tolist()


def kmeans(X: np.ndarray, k: int, seed: int, iters: int = 50):
    """Plain k-means (Lloyd) over node coordinates -> demand zones."""
    rng = np.random.default_rng(seed)
    C = X[rng.choice(len(X), size=k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((X[:, None, :] - C[None, :, :]) ** 2).sum(-1), axis=1)
        newC = np.array([X[lab == j].mean(0) if np.any(lab == j) else C[j] for j in range(k)])
        if np.allclose(newC, C):
            break
        C = newC
    return lab


def zone_weights(k: int, layout: str, rng: random.Random) -> list[float]:
    if layout == "uniform":
        return [1.0 / k] * k
    if layout == "clustered":  # a few busy zones, the rest quiet: Dirichlet(0.5)
        g = [rng.gammavariate(0.5, 1.0) for _ in range(k)]
        return [x / sum(g) for x in g]
    if layout == "hotspot":  # one zone takes about half of the demand
        w = [1.0] * k
        w[rng.randrange(k)] = k - 1
        return [x / sum(w) for x in w]
    raise ValueError(f"layout must be one of {LAYOUTS}")


class OrderSampler:
    """Holds the map zones and distributions; makes one order at a time or a whole scenario.

    The same sampler serves the start-of-run orders (generate) and single orders arriving during the
    run (generate_order). TODO(R1): call generate_order(self.rng, t) in events._emit_new_order and
    pass the result to env.add_order().
    """

    def __init__(
        self,
        emp,
        nodes: pd.DataFrame,
        layout: str = "uniform",
        zone_seed: int = 0,
        depot_nodes=(),
        n_zones: int = 8,
        start_s: float = SIM_START_S,
        end_s: float = SIM_END_S,
        min_tw_width_s: float = 30 * 60,
    ):
        self.emp, self.layout = emp, layout
        self.start_s, self.end_s, self.min_w = start_s, end_s, min_tw_width_s
        cand = nodes[~nodes["node"].isin(list(depot_nodes))].reset_index(drop=True)
        self.nodes = [int(n) for n in cand["node"]]
        lab = kmeans(cand[["x", "y"]].to_numpy(float), n_zones, zone_seed)
        self.zone_nodes = [
            [self.nodes[i] for i in np.flatnonzero(lab == j)] for j in range(n_zones)
        ]
        self.zone_w = zone_weights(n_zones, layout, random.Random(zone_seed))
        self._counter = 0

    def generate_order(self, rng: random.Random, t: float, order_id: str | None = None) -> Order:
        """One new order released at time t (seconds since midnight)."""
        emp = self.emp
        if order_id is None:
            self._counter += 1
            order_id = f"dyn_{self._counter}"
        zone = rng.choices(range(len(self.zone_nodes)), weights=self.zone_w)[0]
        node = rng.choice(self.zone_nodes[zone] or self.nodes)

        n_pk = int(rng.choice(emp.packages_per_stop))
        vol = sum(rng.choice(emp.volume) for _ in range(n_pk))
        demand = float(max(1, math.ceil(vol / emp.unit_cm3)))
        priority = rng.choices((1, 2, 3), weights=PRIORITY_SPLIT)[0]

        tw_start, tw_end = NO_TW_START, NO_TW_END  # no window (R1's defaults)
        if emp.tw_width_h and rng.random() < emp.p_tw:
            width = max(self.min_w, float(rng.choice(emp.tw_width_h)) * 3600)
            offset_h = float(rng.choice(emp.tw_offset_h)) if emp.tw_offset_h else 0.0
            span = self.end_s - self.start_s
            # rescale the Amazon offset (spread over a ~10 h day) into our 4 h period
            tw_start = t + max(0.0, offset_h) * 3600 * span / (AMAZON_ROUTE_H * 3600)
            tw_start = max(t, min(tw_start, self.end_s - self.min_w))  # never before release
            tw_end = min(tw_start + width, self.end_s)

        return Order(
            id=order_id,
            node=int(node),
            demand=demand,
            priority=int(priority),
            tw_start=tw_start,
            tw_end=tw_end,
            service_time=float(rng.choice(emp.service_s)),
            release_time=float(t),
        )

    def generate(
        self, n_orders: int, seed: int, dynamic_share: float = DYNAMIC_SHARE
    ) -> list[Order]:
        """A scenario's orders: most known at 06:00, dynamic_share released during the run (D3)."""
        rng = random.Random(seed)
        orders = []
        for i in range(n_orders):
            dynamic = rng.random() < dynamic_share
            t = self.start_s + (
                rng.uniform(0, 0.75 * (self.end_s - self.start_s)) if dynamic else 0.0
            )
            orders.append(self.generate_order(rng, t, order_id=f"O{i:04d}"))
        return orders


def generate(emp, nodes, n_orders, seed, layout="uniform", depot_nodes=(), **kw) -> list[Order]:
    """Convenience: one call for a whole scenario (same seed -> same orders)."""
    return OrderSampler(emp, nodes, layout, zone_seed=seed, depot_nodes=depot_nodes, **kw).generate(
        n_orders, seed
    )


def order_summary(orders) -> dict:
    """Counts used in the CLI output and the data profile doc."""
    with_tw = [o for o in orders if tw_of(o) is not None]
    return {
        "orders": len(orders),
        "with_time_window": len(with_tw),
        "without_time_window": len(orders) - len(with_tw),
        "dynamic": sum(o.release_time > SIM_START_S for o in orders),
        "priority_counts": {p: sum(o.priority == p for o in orders) for p in (1, 2, 3)},
        "total_demand": sum(o.demand for o in orders),
    }


def compare_to_empirical(orders, emp) -> dict:
    """Definition of Done check: generated statistics match the empirical ones (KS test)."""
    from scipy.stats import ks_2samp

    out = {"service_time": ks_2samp([o.service_time for o in orders], emp.service_s).pvalue}
    widths = [(tw[1] - tw[0]) / 3600 for tw in map(tw_of, orders) if tw]
    if len(widths) > 5:
        # widths are clipped to the period, so expect a lower p-value here; report it, don't hide it
        out["tw_width_h"] = ks_2samp(widths, emp.tw_width_h).pvalue
    out["share_with_tw_generated"] = float(np.mean([tw_of(o) is not None for o in orders]))
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
    orders = generate(emp, pd.read_csv(a.nodes), a.n_orders, a.seed, a.layout, depot_nodes=a.depots)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "seed": a.seed,
        "layout": a.layout,
        "unit_cm3": emp.unit_cm3,
        "source": "Amazon Last Mile 2021 statistics (CC BY-NC 4.0)",
    }
    with open(a.out, "w") as f:
        json.dump({"meta": meta, "orders": [asdict(o) for o in orders]}, f, indent=1)
    print(f"wrote {len(orders)} orders to {a.out}")
    print("summary:", order_summary(orders))
    print("match vs empirical (KS p-values):", compare_to_empirical(orders, emp))


if __name__ == "__main__":
    main()
