"""Traffic ground truth for the simulator (R6).

MULT[edge, 5-minute step] = how many times slower than free-flow an edge is.
Source patterns are real METR-LA sensors from the TEST period only.
Assumptions (state them in the report):
  * LA rush hours are shifted +1 hour to approximate Hyderabad.
  * Road class -> sensor group (strong / medium / mild rush-hour dip).
  * Edges in the same ~500 m zone share spatially correlated noise.
  * Gaps in sensor data are forward/back filled (ground truth needs no gaps).
"""
import numpy as np
import pandas as pd
from src.prediction.data_prep import prepare_ratio
from src.world.edge_table import load_edge_table

STEP_S = 300
GLOBAL_SHIFT_STEPS = 12          # +1 hour
SIM_START = "2012-06-05"         # first full day inside the test split
MAX_MULT = 6.0
GROUP_OF_CLASS = {"motorway": "strong", "trunk": "strong", "primary": "strong",
                  "secondary": "medium", "tertiary": "medium"}   # rest: mild


def sensor_groups(train):
    """Split sensors into mild/medium/strong by weekday rush-hour dip (train only)."""
    h = train.index.hour
    peak = (train.index.dayofweek < 5) & (((h >= 7) & (h < 9)) | ((h >= 16) & (h < 18)))
    dip = train.mean() - train[peak].mean()
    order = list(dip.sort_values().index)
    k = len(order) // 3
    return {"mild": order[:k], "medium": order[k:2 * k], "strong": order[2 * k:]}


class TrafficModel:
    def __init__(self, edges, road_classes, zone_of_edge, seed=42):
        self.edges = list(edges)
        self.edge_index = {e: i for i, e in enumerate(self.edges)}
        ratio, train, val, test = prepare_ratio()
        rng = np.random.default_rng(seed)
        groups = sensor_groups(train)
        cols = {c: i for i, c in enumerate(test.columns)}

        arr = test.ffill().bfill().fillna(1.0).to_numpy(dtype=np.float32)
        start = test.index.get_loc(pd.Timestamp(SIM_START))
        self.n_steps = ((len(arr) - start) // 288) * 288
        n_edges = len(self.edges)

        sensors = np.empty(n_edges, dtype=int)
        for e, cls in enumerate(road_classes):
            g = groups[GROUP_OF_CLASS.get(cls, "mild")]
            sensors[e] = cols[g[rng.integers(len(g))]]
        shifts = rng.integers(0, 3, size=n_edges)          # 0-10 min per-edge offset

        base = start - GLOBAL_SHIFT_STEPS + np.arange(self.n_steps)
        ratios = arr[base[None, :] - shifts[:, None], sensors[:, None]]

        zone_of_edge = np.asarray(zone_of_edge)
        n_zones = int(zone_of_edge.max()) + 1
        kernel = np.ones(6) / 6
        zone_noise = np.stack([
            np.convolve(rng.normal(0, 0.08, self.n_steps + 5), kernel, mode="valid")
            for _ in range(n_zones)]).astype(np.float32)
        ratios = ratios + zone_noise[zone_of_edge]
        ratios += 0.01 * rng.standard_normal(ratios.shape, dtype=np.float32)
        ratios = np.clip(ratios, 0.05, 1.0)
        self.mult = np.clip(1.0 / ratios, 1.0, MAX_MULT).astype(np.float32)

    @classmethod
    def from_graph(cls, path="data/processed/secunderabad.graphml", seed=42):
        edges, classes, zones = load_edge_table(path)
        m = cls(edges, classes, zones, seed)
        m.road_classes = classes
        return m

    def actual_multiplier(self, edge_idx, t_seconds):
        """Congestion multiplier (>= 1) for an edge index at simulated time t (s)."""
        return float(self.mult[edge_idx, int(t_seconds // STEP_S) % self.n_steps])

    def actual_multiplier_uv(self, u, v, t_seconds):
        """Same, addressed by (u, v) node ids (strings, as in the GraphML file)."""
        return self.actual_multiplier(self.edge_index[(u, v)], t_seconds)


if __name__ == "__main__":
    m = TrafficModel.from_graph()
    cls = np.array(m.road_classes)
    print("edges:", len(m.edges), "| table:", m.mult.shape, "| days:", m.n_steps // 288)
    print("min multiplier:", m.mult.min(), "(must be >= 1)")
    for c in ["primary", "secondary", "residential"]:
        rows = np.where(cls == c)[0]
        prof = [m.mult[rows][:, h * 12 + 288 * 7].mean() for h in (3, 9, 13, 18, 22)]
        print(f"{c:12s} ({len(rows)} edges) mean multiplier at 03,09,13,18,22h:",
              np.round(prof, 2))
    m2 = TrafficModel.from_graph()
    print("deterministic:", np.array_equal(m.mult, m2.mult))
