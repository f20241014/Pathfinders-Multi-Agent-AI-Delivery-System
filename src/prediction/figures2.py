"""Predicted-vs-actual curve and ablation bar chart (R6)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from src.prediction.predictor import Predictor
from src.world.traffic_model import TrafficModel

OUT = "reports/figures/"
tm = TrafficModel.from_graph()
p = Predictor(tm)
cls = np.array(tm.road_classes)
e = int(np.where(cls == "primary")[0][0])
day = 7 * 288 * 300
ts = [day + 6 * 3600 + k * 300 for k in range(0, 12 * 8)]
actual = [tm.actual_multiplier(e, t + 900) for t in ts]
pred = [p.predict(e, t, 15) for t in ts]
hrs = [(t - day) / 3600 for t in ts]
plt.figure(figsize=(7, 4))
plt.plot(hrs, actual, label="Actual (15 min ahead)")
plt.plot(hrs, pred, label="Predicted (LSTM, 15 min)")
plt.xlabel("Simulated hour of day"); plt.ylabel("Congestion multiplier")
plt.title("Predicted vs actual, one primary road"); plt.legend()
plt.savefig(OUT + "pred_vs_actual.png", dpi=150, bbox_inches="tight"); plt.close()

df = pd.read_csv("reports/ablation_predictor_pilot.csv")
g = df.groupby(["rate", "predictor"]).mean_delivery_s.mean().unstack()
g[["off", "on"]].plot(kind="bar", figsize=(5, 4))
plt.ylabel("Mean delivery time (s), pilot 5 seeds")
plt.title("Replanning without vs with forecast (08:00 start)")
plt.xticks(rotation=0)
plt.savefig(OUT + "ablation_bars.png", dpi=150, bbox_inches="tight"); plt.close()
print("saved 2 figures")
