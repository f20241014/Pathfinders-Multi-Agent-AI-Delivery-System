"""Clean METR-LA and build the speed ratio with a chronological split.

ratio = speed / free-flow speed. Free-flow is the 95th percentile of each
sensor's speeds, computed from TRAIN rows only (no leakage).
"""
import numpy as np
from src.prediction.load_metr_la import load_metr_la

TRAIN_END = 0.7   # first 70% of time = train
VAL_END = 0.8     # next 10% = validation, last 20% = test


def prepare_ratio(path="data/raw/metr-la.h5"):
    df = load_metr_la(path).replace(0, np.nan)    # zeros mean "missing"
    n = len(df)
    i1, i2 = int(TRAIN_END * n), int(VAL_END * n)
    free_flow = df.iloc[:i1].quantile(0.95)       # per sensor, train rows only
    ratio = (df / free_flow).clip(0.05, 1.0)      # NaN stays NaN
    return ratio, ratio.iloc[:i1], ratio.iloc[i1:i2], ratio.iloc[i2:]


if __name__ == "__main__":
    ratio, train, val, test = prepare_ratio()
    for name, part in [("train", train), ("val", val), ("test", test)]:
        print(name, part.shape, part.index.min(), "->", part.index.max(),
              "| missing: %.1f%%" % (100 * part.isna().mean().mean()))
    print(ratio.stack().describe())
