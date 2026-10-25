"""Demo and in-simulation accuracy check for the Predictor (R6)."""
import time

import numpy as np

from src.prediction.predictor import Predictor
from src.world.traffic_model import TrafficModel

tm = TrafficModel.from_graph()
p = Predictor(tm)
cls = np.array(tm.road_classes)
t = 9 * 3600 + 7 * 288 * 300
t0 = time.process_time()
p.refresh(t)
print("full-network refresh: %.3f s for %d edges" % (time.process_time() - t0, p.n_edges))
for c in ["primary", "residential"]:
    e = int(np.where(cls == c)[0][0])
    actual = [tm.actual_multiplier(e, t + m * 60) for m in (15, 30, 60)]
    pred = [p.predict(e, t, m) for m in (15, 30, 60)]
    print(c, "actual:", np.round(actual, 2), "pred:", np.round(pred, 2))
allp = p.cache[p.refresh(t)]
print("min predicted multiplier:", allp.min(), "(must be >= 1)")
errs = []
for k, m in enumerate((15, 30, 60)):
    act = np.array([tm.actual_multiplier(i, t + m * 60) for i in range(p.n_edges)])
    errs.append(float(np.abs(allp[:, k] - act).mean()))
print("mean abs multiplier error at 15/30/60 min:", np.round(errs, 3))
