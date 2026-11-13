"""
R3 · Profile the Amazon Last Mile Routing Research Challenge (2021) data.

Getting the data (details in docs/data_profile.md):
    1. download route_data.json and package_data.json from model_build_inputs/ into data/raw/
       (skip travel_times.json, it is the bulk of the download and we use our own map)
    2. python scripts/clean_json.py
       -> data/cleaned/package_data.json (the raw file writes missing values as bare NaN,
          which is not valid JSON and stops the streaming parser)
    3. python -m src.data.profile_amazon --max-routes 500      (drop --max-routes for the full run)

package_data.json is streamed route by route with ijson, so it never sits in memory whole.
route_data.json is smaller and is read with json (which accepts NaN).
Lat/lng are obfuscated in this dataset, so no geography is used.

Outputs (in --out-dir):
    routes.csv, packages_per_stop.csv, packages.csv, stops_per_route.csv
    summary.json  -> numbers for docs/data_profile.md
    *.png         -> histograms for the profile doc
These CSVs are the empirical distributions src/data/orders_from_amazon.py samples from.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd


def parse_ts(s):
    """Amazon timestamps look like '2018-07-27 16:00:00'. Missing windows are NaN/None/''."""
    if s is None or (isinstance(s, float) and math.isnan(s)) or s in ("", "nan", "NaN"):
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(x) else x


def _stream_packages(path: Path, wanted: set):
    """Yield (route_id, stops) from package_data.json one route at a time."""
    import ijson

    with open(path, "rb") as f:
        for rid, stops in ijson.kvitems(f, "", use_float=True):
            if rid in wanted:
                yield rid, stops


def profile(route_file: Path, package_file: Path, max_routes: int | None = None):
    with open(route_file) as f:
        routes = json.load(f)
    route_ids = list(routes)[:max_routes] if max_routes else list(routes)
    wanted = set(route_ids)

    route_rows, stop_rows, pkg_rows = [], [], []
    for rid, pk_stops in _stream_packages(package_file, wanted):
        r = routes[rid]
        dep_date, dep_time = r.get("date_YYYY_MM_DD"), r.get("departure_time_utc")
        dep = parse_ts(f"{dep_date} {dep_time}") if dep_date and dep_time else None
        stops = r.get("stops", {})
        dropoffs = [s for s, v in stops.items() if v.get("type") != "Station"]

        route_vol = 0.0
        for sid in dropoffs:
            pk = pk_stops.get(sid, {}) or {}
            svc = []
            for p in pk.values():
                d = p.get("dimensions", {}) or {}
                vol = _num(d.get("depth_cm")) * _num(d.get("height_cm")) * _num(d.get("width_cm"))
                route_vol += vol
                tw = p.get("time_window", {}) or {}
                tws, twe = parse_ts(tw.get("start_time_utc")), parse_ts(tw.get("end_time_utc"))
                has_tw = tws is not None and twe is not None
                svc_s = _num(p.get("planned_service_time_seconds"))
                svc.append(svc_s)
                pkg_rows.append(
                    {
                        "route_id": rid,
                        "stop_id": sid,
                        "volume_cm3": vol,
                        "has_tw": has_tw,
                        "tw_width_h": (twe - tws).total_seconds() / 3600 if has_tw else None,
                        # window start relative to route departure (places windows in sim time)
                        "tw_start_after_dep_h": (
                            (tws - dep).total_seconds() / 3600 if has_tw and dep else None
                        ),
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
                    "service_max_s": max(svc) if svc else 0.0,
                }
            )
        cap = _num(r.get("executor_capacity_cm3"))
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
    return pd.DataFrame(route_rows), pd.DataFrame(stop_rows), pd.DataFrame(pkg_rows)


def _q(series):
    s = series.dropna().astype(float)
    if s.empty:
        return {"n": 0}
    out = {str(k): round(float(v), 3) for k, v in s.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).items()}
    return out | {"mean": round(float(s.mean()), 3), "n": int(s.size)}


def summarise(R, S, P) -> dict:
    return {
        "n_routes": len(R),
        "stations": int(R["station"].nunique()),
        "stops_per_route": _q(R["n_stops"]),
        "packages_per_stop": _q(S["n_packages"]),
        "package_volume_cm3": _q(P["volume_cm3"]),
        "share_packages_with_tw": round(float(P["has_tw"].mean()), 4),
        "share_stops_with_any_tw": round(
            float(P.groupby(["route_id", "stop_id"])["has_tw"].any().mean()), 4
        ),
        "tw_width_h": _q(P["tw_width_h"]),
        "tw_start_after_departure_h": _q(P["tw_start_after_dep_h"]),
        "service_time_per_stop_s(sum)": _q(S["service_sum_s"]),
        "service_time_per_stop_s(max)": _q(S["service_max_s"]),
        "capacity_utilization": _q(R["utilization"]),
        "departure_hour_utc_counts": {
            str(k): int(v) for k, v in R["departure_hour_utc"].value_counts().sort_index().items()
        },
        "route_score_counts": {str(k): int(v) for k, v in R["route_score"].value_counts().items()},
    }


def write_outputs(R, S, P, out: Path, plots: bool = True) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    R.to_csv(out / "routes.csv", index=False)
    S.to_csv(out / "packages_per_stop.csv", index=False)
    P.to_csv(out / "packages.csv", index=False)
    R[["route_id", "n_stops"]].to_csv(out / "stops_per_route.csv", index=False)
    summary = summarise(R, S, P)
    with open(out / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    if plots:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        for series, title, fname, logy in [
            (R["n_stops"], "Stops per route", "stops_per_route.png", False),
            (S["n_packages"], "Packages per stop", "packages_per_stop.png", False),
            (P["volume_cm3"], "Package volume (cm³)", "package_volume.png", True),
            (P["tw_width_h"], "Time-window width (h)", "tw_width.png", False),
            (S["service_sum_s"], "Service time per stop (s)", "service_time.png", True),
        ]:
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
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route-file", default="data/raw/route_data.json")
    ap.add_argument(
        "--package-file",
        default="data/cleaned/package_data.json",
        help="output of scripts/clean_json.py",
    )
    ap.add_argument("--out-dir", default="data/profile")
    ap.add_argument("--max-routes", type=int, default=None, help="profile a subset to save time")
    a = ap.parse_args()
    for p in (a.route_file, a.package_file):
        if not Path(p).exists():
            raise SystemExit(f"{p} not found: see the steps at the top of this file")
    R, S, P = profile(Path(a.route_file), Path(a.package_file), a.max_routes)
    summary = write_outputs(R, S, P, Path(a.out_dir))
    print(json.dumps(summary, indent=2))
    print(f"wrote CSVs, summary.json and plots to {a.out_dir}")


if __name__ == "__main__":
    main()
