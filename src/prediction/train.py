"""Train a shared LSTM on METR-LA speed ratios and compare with baselines.

Input: last 12 steps (ratio + sin/cos time of day + weekday). Output: ratio at
+3, +6, +12 steps, predicted as (current ratio + learned change).
Training targets lie fully inside train; val targets inside val.
All three methods are scored on identical test cells.
"""
import json
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from src.prediction.data_prep import prepare_ratio
from src.prediction.baselines import hist_table, slot

CFG = dict(seed=42, win=12, horizons=[3, 6, 12], hidden=64, layers=2,
           dropout=0.1, batch=512, steps_per_epoch=400, epochs=25,
           patience=4, lr=1e-3)
H = CFG["horizons"]
WIN = CFG["win"]


class Forecaster(nn.Module):
    def __init__(self, mu, sd):
        super().__init__()
        self.mu, self.sd = mu, sd
        self.rnn = nn.LSTM(4, CFG["hidden"], CFG["layers"], batch_first=True,
                           dropout=CFG["dropout"])
        self.head = nn.Linear(CFG["hidden"], len(H))

    def forward(self, x):
        out, _ = self.rnn(x)
        last_ratio = x[:, -1, 0] * self.sd + self.mu      # undo normalisation
        return last_ratio[:, None] + self.head(out[:, -1])


def masked_mae(pred, y):
    m = ~torch.isnan(y)
    return (pred - torch.nan_to_num(y)).abs().mul(m).sum() / m.sum().clamp(min=1)


def make_batch(t, s, filled_n, raw_pad, feats):
    idx = t[:, None] + np.arange(-WIN + 1, 1)[None, :]            # B x 12
    x = np.concatenate([filled_n[idx, s[:, None]][..., None], feats[idx]], 2)
    y = np.stack([raw_pad[t + h, s] for h in H], 1)               # NaN = missing
    return torch.from_numpy(x.astype(np.float32)), torch.from_numpy(y)


def main():
    torch.manual_seed(CFG["seed"])
    rng = np.random.default_rng(CFG["seed"])
    ratio, train, val, test = prepare_ratio()
    n, i1, i2 = len(ratio), len(train), len(train) + len(val)
    S = ratio.shape[1]

    raw = ratio.to_numpy(np.float32)                              # NaN = missing
    raw_pad = np.concatenate([raw, np.full((max(H), S), np.nan, np.float32)])
    filled = ratio.ffill().fillna(1.0).to_numpy(np.float32)       # causal fill
    mu, sd = float(np.nanmean(raw[:i1])), float(np.nanstd(raw[:i1]))   # TRAIN only
    filled_n = (filled - mu) / sd
    idx = ratio.index
    tod = (idx.hour * 60 + idx.minute) / 1440.0
    feats = np.stack([np.sin(2 * np.pi * tod), np.cos(2 * np.pi * tod),
                      idx.dayofweek / 6.0], 1).astype(np.float32)

    model = Forecaster(mu, sd)
    opt = torch.optim.Adam(model.parameters(), lr=CFG["lr"])

    # fixed validation sample (targets fully inside val)
    vr = np.random.default_rng(123)
    vt = vr.integers(i1, i2 - max(H), 60000)
    vs = vr.integers(0, S, 60000)
    vx, vy = make_batch(vt, vs, filled_n, raw_pad, feats)

    best, bad, best_state = 1e9, 0, None
    for ep in range(CFG["epochs"]):
        model.train()
        for _ in range(CFG["steps_per_epoch"]):
            t = rng.integers(WIN - 1, i1 - max(H), CFG["batch"])   # targets stay in train
            s = rng.integers(0, S, CFG["batch"])
            x, y = make_batch(t, s, filled_n, raw_pad, feats)
            opt.zero_grad()
            loss = masked_mae(model(x), y)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            v = masked_mae(model(vx), vy).item()
        print(f"epoch {ep + 1:2d} | last train batch {loss.item():.4f} | val MAE {v:.4f}")
        if v < best - 1e-5:
            best, bad = v, 0
            best_state = {k: p.clone() for k, p in model.state_dict().items()}
        else:
            bad += 1
            if bad >= CFG["patience"]:
                print("early stop")
                break
    model.load_state_dict(best_state)
    model.eval()

    # ---- test: all test origins x all sensors, same cells for every method
    N = len(test)
    preds = np.zeros((N, S, len(H)), np.float32)
    with torch.no_grad():
        for a in range(0, N, 200):
            ts = np.arange(i2 + a, i2 + min(a + 200, N))
            t = np.repeat(ts, S)
            s = np.tile(np.arange(S), len(ts))
            x, _ = make_batch(t, s, filled_n, raw_pad, feats)
            preds[a:a + len(ts)] = model(x).numpy().reshape(len(ts), S, len(H))

    table = hist_table(train)
    rows = []
    for k, h in enumerate(H):
        target = raw_pad[i2 + h: i2 + h + N]                       # N x S
        ok = ~np.isnan(target)
        t_idx = test.index + pd.Timedelta(minutes=5 * h)
        keys = pd.MultiIndex.from_arrays([t_idx.dayofweek, slot(t_idx)])
        hist = table.reindex(keys).to_numpy()
        persist = filled[i2:i2 + N]

        def m(p):
            return float(np.abs(p - target)[ok & ~np.isnan(p)].mean())
        rows.append({"horizon_min": 5 * h,
                     "persistence_MAE": round(m(persist), 4),
                     "hist_avg_MAE": round(m(hist), 4),
                     "lstm_MAE": round(m(preds[:, :, k]), 4)})
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    out.to_csv("reports/model_mae.csv", index=False)
    torch.save({"state": model.state_dict(), "mu": mu, "sd": sd, "cfg": CFG},
               "models/lstm_v1.pt")
    with open("reports/lstm_v1_config.json", "w") as f:
        json.dump({**CFG, "best_val_mae": best}, f, indent=2)


if __name__ == "__main__":
    main()
