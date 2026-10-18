"""Predictor interface for planners (R6).

predict(edge_idx, t_now_s, horizon_min) -> predicted multiplier (>= 1).
predicted_time(edge_idx, t_now_s, horizon_min, free_flow_s) -> seconds.

Method per horizon (from reports/model_mae.csv on the test split):
  15, 30 min -> LSTM ; 60 min -> historical average (it was better there).
The network runs ONCE per 5-minute step for all edges (batched), then results
are cached, so each predict() call is an array lookup.
Inputs are only what has already happened by t_now (past hour of ratios).
"""
import numpy as np
import torch
from src.prediction.data_prep import prepare_ratio
from src.prediction.baselines import hist_table, slot
from src.prediction.train import Forecaster, CFG
from src.world.traffic_model import TrafficModel, STEP_S, SIM_START, GLOBAL_SHIFT_STEPS
import pandas as pd

WIN = CFG["win"]
H_STEPS = {15: 0, 30: 1, 60: 2}          # column in the model output
MAX_MULT = 6.0


class Predictor:
    def __init__(self, traffic, model_path="models/lstm_v1.pt"):
        ck = torch.load(model_path, weights_only=False)
        self.model = Forecaster(ck["mu"], ck["sd"])
        self.model.load_state_dict(ck["state"])
        self.model.eval()
        self.mu, self.sd = ck["mu"], ck["sd"]
        self.tm = traffic
        ratio, train, _, test = prepare_ratio()
        self.table = hist_table(train)
        # clock: simulated step 0 = SIM_START midnight (a real test-period day)
        self.t0 = pd.Timestamp(SIM_START) - pd.Timedelta(minutes=5 * GLOBAL_SHIFT_STEPS)  # LA clock
        self.cache = {}                        # step -> array [n_edges, 3]
        self.n_edges = traffic.mult.shape[0]
        # the sensor-style ratio history seen by the fleet = 1 / true multiplier
        self.hist_ratio = 1.0 / traffic.mult   # [edges, steps]

    def _features(self, step):
        ts = self.t0 + pd.to_timedelta(5 * (step - np.arange(WIN)[::-1]), unit="m")
        tod = (ts.hour * 60 + ts.minute) / 1440.0
        f = np.stack([np.sin(2 * np.pi * tod), np.cos(2 * np.pi * tod),
                      ts.dayofweek / 6.0], 1).astype(np.float32)
        return f                                # [12, 3]

    def _compute(self, step):
        n = self.hist_ratio.shape[1]
        idx = (step - np.arange(WIN)[::-1]) % n
        r = self.hist_ratio[:, idx]             # [edges, 12] past hour
        rn = ((r - self.mu) / self.sd).astype(np.float32)
        f = np.broadcast_to(self._features(step), (self.n_edges, WIN, 3))
        x = np.concatenate([rn[..., None], f], 2)
        with torch.no_grad():
            ratio_pred = self.model(torch.from_numpy(x)).numpy()   # [edges, 3]
        out = np.empty_like(ratio_pred)
        out[:, :2] = ratio_pred[:, :2]                             # LSTM: 15, 30
        # historical average for 60 min: same slot, one hour ahead, per edge
        t_target = self.t0 + pd.Timedelta(minutes=5 * (step + 12))
        key = (t_target.dayofweek, t_target.hour * 12 + t_target.minute // 5)
        row = self.table.loc[key].to_numpy()                       # sensor means
        out[:, 2] = np.clip(self._edge_hist(row), 0.05, 1.0)
        out[:, :2] = np.clip(out[:, :2], 0.05, 1.0)
        return np.clip(1.0 / out, 1.0, MAX_MULT)

    def _edge_hist(self, sensor_row):
        """Edge version of the 60-min historical average (mean over all sensors
        in the same group as the edge's class); simple and documented."""
        if not hasattr(self, "_grp_mean"):
            from src.world.traffic_model import sensor_groups
            ratio, train, _, _ = prepare_ratio()
            g = sensor_groups(train)
            cols = {c: i for i, c in enumerate(train.columns)}
            self._gidx = {k: [cols[c] for c in v] for k, v in g.items()}
        m = {k: float(sensor_row[v].mean()) for k, v in self._gidx.items()}
        from src.world.traffic_model import GROUP_OF_CLASS
        return np.array([m[GROUP_OF_CLASS.get(c, "mild")]
                         for c in self.tm.road_classes])

    def refresh(self, t_now_s):
        step = int(t_now_s // STEP_S)
        if step not in self.cache:
            self.cache = {step: self._compute(step)}   # keep only the latest
        return step

    def predict(self, edge_idx, t_now_s, horizon_min=15):
        step = self.refresh(t_now_s)
        return float(self.cache[step][edge_idx, H_STEPS[horizon_min]])

    def predicted_time(self, edge_idx, t_now_s, horizon_min, free_flow_s):
        return free_flow_s * self.predict(edge_idx, t_now_s, horizon_min)


if __name__ == "__main__":
    import time
    tm = TrafficModel.from_graph()
    p = Predictor(tm)
    cls = np.array(tm.road_classes)
    t = 9 * 3600 + 7 * 288 * 300               # 9 am on simulated day 8
    t0 = time.process_time()
    p.refresh(t)
    print("full-network refresh: %.3f s for %d edges" % (time.process_time() - t0, p.n_edges))
    for c in ["primary", "residential"]:
        e = int(np.where(cls == c)[0][0])
        actual = [tm.actual_multiplier(e, t + m * 60) for m in (15, 30, 60)]
        pred = [p.predict(e, t, m) for m in (15, 30, 60)]
        print(c, "actual:", np.round(actual, 2), "pred:", np.round(pred, 2))
    allp = np.concatenate([p.cache[p.refresh(t)]], 0)
    print("min predicted multiplier:", allp.min(), "(must be >= 1)")
    errs = []
    for k, m in enumerate((15, 30, 60)):
        act = np.array([tm.actual_multiplier(i, t + m * 60) for i in range(p.n_edges)])
        errs.append(float(np.abs(allp[:, k] - act).mean()))
    print("mean abs multiplier error at 15/30/60 min:", np.round(errs, 3))
