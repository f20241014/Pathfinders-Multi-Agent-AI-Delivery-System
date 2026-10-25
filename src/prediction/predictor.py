"""Predictor interface for planners (R6).

predict(edge_idx, t_now_s, horizon_min) -> predicted multiplier (>= 1).
predicted_time(edge_idx, t_now_s, horizon_min, free_flow_s) -> seconds.

Method per horizon: 15, 30 min -> LSTM ; 60 min -> historical average.
The network runs once per 5-minute step for all edges (batched); the last 8
steps are cached, so each predict() call is an array lookup.
Inputs are only what has already happened by t_now (past hour of ratios).
"""
from collections import OrderedDict

import numpy as np
import pandas as pd
import torch

from src.prediction.baselines import hist_table
from src.prediction.data_prep import prepare_ratio
from src.prediction.train import CFG, Forecaster
from src.world.traffic_model import (GLOBAL_SHIFT_STEPS, GROUP_OF_CLASS,
                                     SIM_START, STEP_S, TrafficModel,
                                     sensor_groups)

WIN = CFG["win"]
H_STEPS = {15: 0, 30: 1, 60: 2}
MAX_MULT = 6.0
CACHE_STEPS = 8


class Predictor:
    def __init__(self, traffic, model_path="models/lstm_v1.pt"):
        ck = torch.load(model_path, weights_only=True)
        self.model = Forecaster(ck["mu"], ck["sd"])
        self.model.load_state_dict(ck["state"])
        self.model.eval()
        self.mu, self.sd = ck["mu"], ck["sd"]
        self.tm = traffic
        _, train, _, _ = prepare_ratio()
        self.table = hist_table(train)
        cols = {c: i for i, c in enumerate(train.columns)}
        groups = sensor_groups(train)
        self._gidx = {k: [cols[c] for c in v] for k, v in groups.items()}
        self._edge_group = [GROUP_OF_CLASS.get(c, "mild")
                            for c in traffic.road_classes]
        self.t0 = (pd.Timestamp(SIM_START)
                   - pd.Timedelta(minutes=5 * GLOBAL_SHIFT_STEPS))
        self.cache = OrderedDict()
        self.n_edges = traffic.mult.shape[0]
        self.hist_ratio = 1.0 / traffic.mult

    def _features(self, step):
        ts = self.t0 + pd.to_timedelta(5 * (step - np.arange(WIN)[::-1]), unit="m")
        tod = (ts.hour * 60 + ts.minute) / 1440.0
        return np.stack([np.sin(2 * np.pi * tod), np.cos(2 * np.pi * tod),
                         ts.dayofweek / 6.0], 1).astype(np.float32)

    def _compute(self, step):
        n = self.hist_ratio.shape[1]
        idx = np.maximum(step - np.arange(WIN)[::-1], 0) % n
        r = self.hist_ratio[:, idx]
        rn = ((r - self.mu) / self.sd).astype(np.float32)
        f = np.broadcast_to(self._features(step), (self.n_edges, WIN, 3))
        x = np.concatenate([rn[..., None], f], 2)
        with torch.no_grad():
            ratio_pred = self.model(torch.from_numpy(x)).numpy()
        out = np.empty_like(ratio_pred)
        out[:, :2] = np.clip(ratio_pred[:, :2], 0.05, 1.0)
        t_target = self.t0 + pd.Timedelta(minutes=5 * (step + 12))
        key = (t_target.dayofweek, t_target.hour * 12 + t_target.minute // 5)
        row = self.table.loc[key].to_numpy()
        gm = {k: float(row[v].mean()) for k, v in self._gidx.items()}
        out[:, 2] = np.clip([gm[g] for g in self._edge_group], 0.05, 1.0)
        return np.clip(1.0 / out, 1.0, MAX_MULT)

    def refresh(self, t_now_s):
        step = int(t_now_s // STEP_S)
        if step in self.cache:
            self.cache.move_to_end(step)
        else:
            self.cache[step] = self._compute(step)
            while len(self.cache) > CACHE_STEPS:
                self.cache.popitem(last=False)
        return step

    def predict(self, edge_idx, t_now_s, horizon_min=15):
        if horizon_min not in H_STEPS:
            raise ValueError("horizon_min must be one of 15, 30, 60")
        step = self.refresh(t_now_s)
        return float(self.cache[step][edge_idx, H_STEPS[horizon_min]])

    def predicted_time(self, edge_idx, t_now_s, horizon_min, free_flow_s):
        return free_flow_s * self.predict(edge_idx, t_now_s, horizon_min)
