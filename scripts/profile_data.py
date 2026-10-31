
import ijson
import math
from pathlib import Path
from datetime import datetime
import numpy as np

RAW = Path("data/cleaned")

def is_missing(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("", "nan", "none")
    if isinstance(value, float):
        return math.isnan(value)
    return False

def print_summary(name, values, unit=""):
    values = [float(x) for x in values if x is not None and math.isfinite(float(x))]

    print(f"\n{name}")
    if not values:
        print("No valid observations")
        return

    a = np.array(values)
    print("Count:", len(a))
    print("Mean:", round(float(np.mean(a)), 2), unit)
    print("Median:", round(float(np.median(a)), 2), unit)
    print("Minimum:", round(float(np.min(a)), 2), unit)
    print("Maximum:", round(float(np.max(a)), 2), unit)
    print("Q1:", round(float(np.percentile(a, 25)), 2), unit)
    print("Q3:", round(float(np.percentile(a, 75)), 2), unit)

# ------------------------------------------------
# 1. PROFILE ROUTE DATA
# ------------------------------------------------

route_file = RAW / "route_data.json"

route_count = 0
stop_counts = []
capacities = []
route_scores = {}
stop_types = {}
zone_counts = {}

print("\n========== ROUTE DATA ==========")

with route_file.open("rb") as f:
    for route_id, route in ijson.kvitems(f, ""):
        route_count += 1

        capacity = route.get("executor_capacity_cm3")
        if not is_missing(capacity):
            capacities.append(float(capacity))

        score = route.get("route_score")
        route_scores[str(score)] = route_scores.get(str(score), 0) + 1

        stops = route.get("stops") or {}
        stop_counts.append(len(stops))

        for stop in stops.values():
            stop_type = stop.get("type", "Unknown")
            zone = stop.get("zone_id", "Unknown")

            stop_types[stop_type] = stop_types.get(stop_type, 0) + 1
            zone_counts[zone] = zone_counts.get(zone, 0) + 1

print("Total routes:", route_count)
print("Total stops:", sum(stop_counts))

print_summary("Stops per route", stop_counts)
print_summary("Vehicle capacity (cm3)", capacities)

print("\nRoute score counts:", route_scores)
print("Stop type counts:", stop_types)
print("Number of distinct zones:", len(zone_counts))

# ------------------------------------------------
# 2. PROFILE PACKAGE DATA
# ------------------------------------------------

package_file = RAW / "package_data.json"

package_count = 0
service_times = []
depths = []
heights = []
widths = []
window_widths = []

missing_windows = 0
complete_windows = 0
invalid_windows = 0

print("\n========== PACKAGE DATA ==========")

with package_file.open("rb") as f:
    for route_id, stops in ijson.kvitems(f, ""):
        if not isinstance(stops, dict):
            continue

        for stop_id, packages in stops.items():
            if not isinstance(packages, dict):
                continue

            for package_id, package in packages.items():
                package_count += 1

                service = package.get("planned_service_time_seconds")
                if not is_missing(service):
                    service_times.append(float(service))

                dimensions = package.get("dimensions") or {}

                for field, values in [
                    ("depth_cm", depths),
                    ("height_cm", heights),
                    ("width_cm", widths)
                ]:
                    value = dimensions.get(field)
                    if not is_missing(value):
                        values.append(float(value))

                window = package.get("time_window") or {}
                start = window.get("start_time_utc")
                end = window.get("end_time_utc")

                if is_missing(start) or is_missing(end):
                    missing_windows += 1
                else:
                    try:
                        start_dt = datetime.fromisoformat(str(start))
                        end_dt = datetime.fromisoformat(str(end))
                        duration = (end_dt - start_dt).total_seconds() / 3600

                        if duration >= 0:
                            window_widths.append(duration)
                            complete_windows += 1
                        else:
                            invalid_windows += 1
                    except (ValueError, TypeError):
                        invalid_windows += 1

print("Total packages:", package_count)
print("Packages with complete time windows:", complete_windows)
print("Packages with missing time windows:", missing_windows)
print("Packages with invalid time windows:", invalid_windows)

if package_count:
    print("Complete time-window share (%):",
          round(complete_windows / package_count * 100, 2))
    print("Missing time-window share (%):",
          round(missing_windows / package_count * 100, 2))

print_summary("Planned service time (seconds)", service_times)
print_summary("Package depth (cm)", depths)
print_summary("Package height (cm)", heights)
print_summary("Package width (cm)", widths)
print_summary("Time-window width (hours)", window_widths)

print("\n========== PROFILING COMPLETE ==========")
