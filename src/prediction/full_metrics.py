"""MAE, RMSE, MAPE per horizon for persistence, historical average, LSTM (test)."""
import numpy as np
import pandas as pd
import torch
from src.prediction.baselines import hist_table, slot
from src.prediction.data_prep import prepare_ratio
from src.prediction.train import Forecaster, H, make_batch

ratio, train, val, test = prepare_ratio()
i2, N, S = len(train) + len(val), len(test), ratio.shape[1]
ck = torch.load("models/lstm_v1.pt", weights_only=True)
model = Forecaster(ck["mu"], ck["sd"])
model.load_state_dict(ck["state"])
model.eval()

raw = ratio.to_numpy(np.float32)
raw_pad = np.concatenate([raw, np.full((max(H), S), np.nan, np.float32)])
filled = ratio.ffill().fillna(1.0).to_numpy(np.float32)
filled_n = (filled - ck["mu"]) / ck["sd"]
idx = ratio.index
tod = (idx.hour * 60 + idx.minute) / 1440.0
feats = np.stack([np.sin(2 * np.pi * tod), np.cos(2 * np.pi * tod),
                  idx.dayofweek / 6.0], 1).astype(np.float32)

preds = np.zeros((N, S, len(H)), np.float32)
with torch.no_grad():
    for a in range(0, N, 200):
        ts = np.arange(i2 + a, i2 + min(a + 200, N))
        t, s = np.repeat(ts, S), np.tile(np.arange(S), len(ts))
        x, _ = make_batch(t, s, filled_n, raw_pad, feats)
        preds[a:a + len(ts)] = model(x).numpy().reshape(len(ts), S, len(H))

table = hist_table(train)
rows = []
for k, h in enumerate(H):
    y = raw_pad[i2 + h:i2 + h + N]
    t_idx = test.index + pd.Timedelta(minutes=5 * h)
    keys = pd.MultiIndex.from_arrays([t_idx.dayofweek, slot(t_idx)])
    methods = {"persistence": filled[i2:i2 + N],
               "hist_avg": table.reindex(keys).to_numpy(),
               "lstm": preds[:, :, k]}
    for name, p in methods.items():
        ok = ~np.isnan(y) & ~np.isnan(p)
        e = (p - y)[ok]
        rows.append({"horizon_min": 5 * h, "method": name,
                     "MAE": round(float(np.abs(e).mean()), 4),
                     "RMSE": round(float(np.sqrt((e ** 2).mean())), 4),
                     "MAPE_%": round(float((np.abs(e) / y[ok]).mean() * 100), 2)})
out = pd.DataFrame(rows)
print(out.to_string(index=False))
out.to_csv("reports/model_metrics_full.csv", index=False)
