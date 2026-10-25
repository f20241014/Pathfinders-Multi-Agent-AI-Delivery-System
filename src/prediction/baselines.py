"""Baselines for the speed-ratio forecast: persistence and historical average.

MAE is computed on the TEST split only, and only where the true future value
exists (missing readings are skipped).
"""
import numpy as np
import pandas as pd
from src.prediction.data_prep import prepare_ratio

HORIZONS = [3, 6, 12]   # steps of 5 min -> 15, 30, 60 minutes


def slot(index):
    """Time-of-day slot (0..287) for each timestamp."""
    return index.hour * 12 + index.minute // 5


def hist_table(train):
    """Mean ratio per (weekday, time slot) per sensor, from TRAIN only."""
    return train.groupby([train.index.dayofweek, slot(train.index)]).mean()


def mae(pred, target):
    """Mean absolute error over cells where both are present."""
    err = (pred - target).abs().to_numpy()
    return float(np.nanmean(err))


def evaluate(test, table, h, current=None):
    target = test.shift(-h)                      # true ratio h steps later
    # persistence: future = now
    persist = mae(test if current is None else current, target)
    # historical average: look up the table at the TARGET time
    t_idx = test.index + pd.Timedelta(minutes=5 * h)
    keys = pd.MultiIndex.from_arrays([t_idx.dayofweek, slot(t_idx)])
    hist_pred = table.reindex(keys)
    hist_pred.index = test.index
    hist = mae(hist_pred, target)
    return persist, hist


if __name__ == "__main__":
    ratio, train, val, test = prepare_ratio()
    table = hist_table(train)
    current = test.ffill()   # same as train.py: forward-filled current value
    rows = []
    for h in HORIZONS:
        p, a = evaluate(test, table, h, current)
        rows.append({"horizon_min": 5 * h, "persistence_MAE": round(p, 4),
                     "hist_avg_MAE": round(a, 4)})
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    out.to_csv("reports/baseline_mae.csv", index=False)
