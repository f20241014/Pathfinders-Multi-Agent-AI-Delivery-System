"""EDA plots for the report: daily cycle, weekday vs weekend, missing data."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from src.prediction.data_prep import prepare_ratio

ratio, _, _, _ = prepare_ratio()
OUT = "reports/figures/"

# 1. Average ratio by hour of day (all sensors)
ratio.mean(axis=1).groupby(ratio.index.hour).mean().plot(marker="o")
plt.xlabel("Hour of day"); plt.ylabel("Mean speed ratio")
plt.title("METR-LA: average speed ratio by hour")
plt.savefig(OUT + "eda_hourly.png", dpi=150, bbox_inches="tight"); plt.close()

# 2. Weekday vs weekend
m = ratio.mean(axis=1)
tab = m.groupby([m.index.dayofweek >= 5, m.index.hour]).mean().unstack(0)
tab.columns = ["Weekday", "Weekend"]
tab.plot(marker="o")
plt.xlabel("Hour of day"); plt.ylabel("Mean speed ratio")
plt.title("Weekday vs weekend")
plt.savefig(OUT + "eda_weekday_weekend.png", dpi=150, bbox_inches="tight"); plt.close()

# 3. Missing data per sensor
(100 * ratio.isna().mean()).plot(kind="hist", bins=30)
plt.xlabel("% missing readings per sensor"); plt.ylabel("Number of sensors")
plt.title("Missing data per sensor")
plt.savefig(OUT + "eda_missing.png", dpi=150, bbox_inches="tight"); plt.close()
print("saved 3 figures to", OUT)
