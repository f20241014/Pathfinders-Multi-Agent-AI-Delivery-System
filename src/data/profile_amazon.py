"""
R3 · Week 1 · Profile the Amazon Last Mile Routing Research Challenge (2021) data.

Usage:
    python src/data/profile_amazon.py --data-dir data/raw/amazon --out-dir data/profile [--max-routes 2000]

Needs only two files from model_build_inputs/ (skip travel_times.json, it is the bulk of the download):
    route_data.json    route-level info + stops (lat/lng are obfuscated -> we do NOT use geography)
    package_data.json  per stop, per package: time window, planned service time, dimensions

Field names below follow the challenge's data-structure doc. If a KeyError appears, open the JSON,
check the real key name, and fix it here (then note it in docs/data_profile.md).

Outputs (in --out-dir):
    stops_per_route.csv, packages_per_stop.csv, packages.csv, routes.csv
    summary.json        -> numbers to paste into docs/data_profile.md
    *.png               -> histograms for the profile doc
These CSVs are also the empirical distributions the Week 2 order generator samples from.
"""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_ts(s):
    """Amazon timestamps look like '2018-07-27 16:00:00'. Missing windows are NaN/None/''."""
    if s is None or (isinstance(s, float) and math.isnan(s)) or s == "" or s == "nan":
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out-dir", default="data/profile")
    ap.add_argument("--max-routes", type=int, default=None, help="profile a subset to save RAM/time")
    args = ap.parse_args()

    data_dir, out = Path(args.data_dir), Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("loading route_data.json ...")
    routes = json.load(open(data_dir / "route_data.json"))
    print("loading package_data.json ...")
    packages = json.load(open(data_dir / "package_data.json"))

    route_ids = list(routes.keys())
    if args.max_routes:
        route_ids = route_ids[: args.max_routes]

    route_rows, stop_rows, pkg_rows = [], [], []
    for rid in route_ids:
        r = routes[rid]
        dep_date = r.get("date_YYYY_MM_DD")
        dep_time = r.get("departure_time_utc")
        dep = parse_ts(f"{dep_date} {dep_time}") if dep_date and dep_time else None
        stops = r.get("stops", {})
        dropoffs = [s for s, v in stops.items() if v.get("type") != "Station"]

        route_vol = 0.0
        for sid in dropoffs:
            pk = packages.get(rid, {}).get(sid, {})
            svc = []
            for pid, p in pk.items():
                d = p.get("dimensions", {}) or {}
                vol = (d.get("depth_cm") or 0) * (d.get("height_cm") or 0) * (d.get("width_cm") or 0)
                route_vol += vol
                tw = p.get("time_window", {}) or {}
                tws, twe = parse_ts(tw.get("start_time_utc")), parse_ts(tw.get("end_time_utc"))
                has_tw = tws is not None and twe is not None
                svc_s = p.get("planned_service_time_seconds")
                svc.append(svc_s or 0)
                pkg_rows.append(
                    {
                        "route_id": rid,
                        "stop_id": sid,
                        "volume_cm3": vol,
                        "has_tw": has_tw,
                        "tw_width_h": (twe - tws).total_seconds() / 3600 if has_tw else None,
                        # where the window starts relative to route departure -> lets us place windows in sim time
                        "tw_start_after_dep_h": (tws - dep).total_seconds() / 3600 if has_tw and dep else None,
                        "service_s": svc_s,
                        "scan_status": p.get("scan_status"),
                    }
                )
            stop_rows.append(
                {
                    "route_id": rid,
                    "stop_id": sid,
                    "zone_id": stops[sid].get("zone_id"),
                    "n_packages": len(pk),
                    # check in the doc whether service time is per package or repeated per stop
                    "service_sum_s": sum(svc),
                    "service_max_s": max(svc) if svc else 0,
                }
            )
        cap = r.get("executor_capacity_cm3")
        route_rows.append(
            {
                "route_id": rid,
                "station": r.get("station_code"),
                "departure_hour_utc": dep.hour if dep else None,
                "n_stops": len(dropoffs),
                "capacity_cm3": cap,
                "load_cm3": route_vol,
                "utilization": route_vol / cap if cap else None,
                "route_score": r.get("route_score"),
            }
        )

    R, S, P = pd.DataFrame(route_rows), pd.DataFrame(stop_rows), pd.DataFrame(pkg_rows)
    R.to_csv(out / "routes.csv", index=False)
    S.to_csv(out / "packages_per_stop.csv", index=False)
    P.to_csv(out / "packages.csv", index=False)
    R[["route_id", "n_stops"]].to_csv(out / "stops_per_route.csv", index=False)

    def q(series):
        s = series.dropna()
        return {k: round(float(v), 3) for k, v in s.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).items()} | {
            "mean": round(float(s.mean()), 3),
            "n": int(s.size),
        }

    summary = {
        "n_routes": len(R),
        "stations": R["station"].nunique(),
        "stops_per_route": q(R["n_stops"]),
        "packages_per_stop": q(S["n_packages"]),
        "package_volume_cm3": q(P["volume_cm3"]),
        "share_packages_with_tw": round(float(P["has_tw"].mean()), 4),
        "share_stops_with_any_tw": round(
            float(P.groupby(["route_id", "stop_id"])["has_tw"].any().mean()), 4
        ),
        "tw_width_h": q(P["tw_width_h"]),
        "tw_start_after_departure_h": q(P["tw_start_after_dep_h"]),
        "service_time_per_stop_s(sum)": q(S["service_sum_s"]),
        "service_time_per_stop_s(max)": q(S["service_max_s"]),
        "capacity_utilization": q(R["utilization"]),
        "departure_hour_utc_counts": R["departure_hour_utc"].value_counts().sort_index().to_dict(),
        "route_score_counts": R["route_score"].value_counts().to_dict(),
    }
    json.dump(summary, open(out / "summary.json", "w"), indent=2, default=str)
    print(json.dumps(summary, indent=2, default=str))

    plots = [
        (R["n_stops"], "Stops per route", "stops_per_route.png", False),
        (S["n_packages"], "Packages per stop", "packages_per_stop.png", False),
        (P["volume_cm3"], "Package volume (cm³)", "package_volume.png", True),
        (P["tw_width_h"], "Time-window width (h)", "tw_width.png", False),
        (S["service_sum_s"], "Service time per stop (s)", "service_time.png", True),
    ]
    for series, title, fname, logy in plots:
        s = series.dropna()
        if s.empty:
            continue
        plt.figure(figsize=(6, 4))
        plt.hist(s, bins=50, log=logy)
        plt.title(title)
        plt.ylabel("count")
        plt.tight_layout()
        plt.savefig(out / fname, dpi=120)
        plt.close()
    print(f"wrote CSVs, summary.json and plots to {out}")


if __name__ == "__main__":
    main()
