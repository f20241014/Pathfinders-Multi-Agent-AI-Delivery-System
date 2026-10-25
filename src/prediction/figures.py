"""Figure F4 (MAE by horizon) and LSTM error by hour of day. R6."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from src.prediction.data_prep import prepare_ratio
from src.prediction.train import Forecaster, make_batch, H, CFG

OUT = "reports/figures/"

# ---- F4: from the logged table
df = pd.read_csv("reports/model_mae.csv")
x = np.arange(len(df))
w = 0.27
plt.figure(figsize=(6, 4))
plt.bar(x - w, df.persistence_MAE, w, label="Persistence")
plt.bar(x, df.hist_avg_MAE, w, label="Historical average")
plt.bar(x + w, df.lstm_MAE, w, label="LSTM")
plt.xticks(x, [f"{m} min" for m in df.horizon_min])
plt.ylabel("Test MAE (speed ratio)")
plt.title("F4: forecast error by horizon (METR-LA test split)")
plt.legend()
plt.savefig(OUT + "F4_mae_by_horizon.png", dpi=150, bbox_inches="tight")
plt.close()

# ---- LSTM error by hour of day (test split)
ratio, train, val, test = prepare_ratio()
i2 = len(train) + len(val)
S = ratio.shape[1]
ck = torch.load("models/lstm_v1.pt", weights_only=False)
model = Forecaster(ck["mu"], ck["sd"])
model.load_state_dict(ck["state"])
model.eval()

raw = ratio.to_numpy(np.float32)
raw_pad = np.concatenate([raw, np.full((max(H), S), np.nan, np.float32)])
filled_n = (ratio.ffill().fillna(1.0).to_numpy(np.float32) - ck["mu"]) / ck["sd"]
idx = ratio.index
tod = (idx.hour * 60 + idx.minute) / 1440.0
feats = np.stack([np.sin(2 * np.pi * tod), np.cos(2 * np.pi * tod),
                  idx.dayofweek / 6.0], 1).astype(np.float32)

N = len(test)
err_sum = np.zeros(24)
err_cnt = np.zeros(24)
k = 0  # horizon index 0 = 15 min
with torch.no_grad():
    for a in range(0, N, 200):
        ts = np.arange(i2 + a, i2 + min(a + 200, N))
        t = np.repeat(ts, S)
        s = np.tile(np.arange(S), len(ts))
        xb, yb = make_batch(t, s, filled_n, raw_pad, feats)
        p = model(xb).numpy()[:, k]
        y = yb.numpy()[:, k]
        ok = ~np.isnan(y)
        hours = idx[t].hour.to_numpy()
        e = np.abs(p - y)
        for hr in range(24):
            sel = ok & (hours == hr)
            err_sum[hr] += e[sel].sum()
            err_cnt[hr] += sel.sum()
by_hour = err_sum / np.maximum(err_cnt, 1)
plt.figure(figsize=(6, 4))
plt.plot(range(24), by_hour, marker="o")
plt.xlabel("Hour of day (LA clock)")
plt.ylabel("LSTM test MAE at 15 min")
plt.title("LSTM error by hour of day")
plt.savefig(OUT + "lstm_error_by_hour.png", dpi=150, bbox_inches="tight")
plt.close()
pd.DataFrame({"hour": range(24), "lstm_mae_15min": by_hour.round(4)}).to_csv(
    "reports/lstm_error_by_hour.csv", index=False)
print(pd.DataFrame({"hour": range(24), "mae": by_hour.round(4)}).to_string(index=False))
print("saved F4 and hourly plot")
