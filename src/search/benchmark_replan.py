"""Week 3 benchmark (R7): D* Lite replanning vs A* from scratch (figure F3).

For each trip on the real Secunderabad graph, D* Lite plans once, then k
roads change (traffic spikes x1.2-3 or closures, the D11 mix of road events)
and both planners find the new route:

* D* Lite repairs its previous search (update_edge_cost + get_path);
* A* (R2's src/search/astar.py) searches again from scratch.

CPU time is time.process_time(), single thread, no plotting while timing
(decision D9). Every pair of answers is checked: equal costs or the run stops.

Where the k changed roads are placed:

* anywhere      - uniform over all roads (what D11's random events do)
* near_vehicle  - on the current route, starting at the vehicle's end
* near_goal     - on the current route, starting at the goal's end

D* Lite searches backwards from the goal, so changes near the goal force it
to redo most of its work: that placement shows where it stops helping.

    python -m src.search.benchmark_replan            # writes CSV + figure
"""

import argparse
import csv
import math
import random
import statistics
import time
from pathlib import Path

from src.search.astar import astar
from src.search.dstar_lite import DStarLite
from src.search.heuristics import make_heuristic

PLACEMENTS = ("anywhere", "near_vehicle", "near_goal")
KS = (1, 2, 5, 10, 20, 50, 100, 200, 500)
CLOSURE_SHARE = 3 / 7          # D11: 30% closures vs 40% spikes among road events
CSV_PATH = Path("reports/dstar_benchmark.csv")
FIG_PATH = Path("reports/figures/F3_dstar_speedup.png")
FIELDS = ["placement", "k", "trip", "dstar_cpu_ms", "astar_cpu_ms",
          "dstar_expanded", "astar_expanded", "cost_s"]


def pick_trips(G, n, rnd, min_roads=10):
    nodes = sorted(G.nodes)
    trips = []
    while len(trips) < n:
        s, t = rnd.sample(nodes, 2)
        res = astar(G, s, t)
        if res.cost < math.inf and len(res.path) - 1 >= min_roads:
            trips.append((s, t))
    return trips


def choose_roads(path, all_roads, k, placement, rnd):
    """k distinct roads; on-route placements fill up with random roads."""
    route = list(zip(path, path[1:]))
    if placement == "near_goal":
        route.reverse()
    picked = [] if placement == "anywhere" else route[:k]
    seen = set(picked)
    while len(picked) < k:
        road = rnd.choice(all_roads)
        if road not in seen:
            seen.add(road)
            picked.append(road)
    return picked


def run(graph_name="secunderabad", trips=20, ks=KS, placements=PLACEMENTS,
        seed=7, use_heuristic=True, G=None):
    """Run the benchmark and return one dict per (placement, k, trip)."""
    if G is None:
        from src.world.graph_loader import load_road_graph
        G = load_road_graph(graph_name)
    h = make_heuristic(G) if use_heuristic else None
    a_h = h if h is not None else (lambda a, b: 0.0)
    rnd = random.Random(seed)
    base = {(u, v): d["free_flow_time"] for u, v, d in G.edges(data=True)}
    all_roads = sorted(base)
    rows = []
    for trip, (s, t) in enumerate(pick_trips(G, trips, rnd)):
        for placement in placements:
            for k in ks:
                d = DStarLite.from_networkx(G, s, t, heuristic=h)
                path = d.get_path()                  # first plan, not timed
                now = dict(base)
                changes = []
                for u, v in choose_roads(path, all_roads, k, placement, rnd):
                    if rnd.random() < CLOSURE_SHARE:
                        now[(u, v)] = math.inf
                    else:
                        now[(u, v)] = base[(u, v)] * rnd.uniform(1.2, 3.0)
                    changes.append((u, v, now[(u, v)]))

                c0 = time.process_time()
                for u, v, c in changes:
                    d.update_edge_cost(u, v, c)
                d_path = d.get_path()
                d_cpu = time.process_time() - c0

                def cost_fn(u, v, data, now=now):
                    return now[(u, v)]
                c0 = time.process_time()
                ref = astar(G, s, t, cost_fn, heuristic=a_h)
                a_cpu = time.process_time() - c0

                got = d.path_cost(d_path)
                if not (got == ref.cost or math.isclose(got, ref.cost, rel_tol=1e-9)):
                    raise AssertionError(
                        f"D* Lite {got} != A* {ref.cost} ({placement}, k={k}, trip={trip})")
                rows.append({
                    "placement": placement, "k": k, "trip": trip,
                    "dstar_cpu_ms": round(d_cpu * 1000, 4),
                    "astar_cpu_ms": round(a_cpu * 1000, 4),
                    "dstar_expanded": d.expanded,
                    "astar_expanded": ref.expanded,
                    "cost_s": round(ref.cost, 3) if ref.cost < math.inf else "inf",
                })
    return rows


def summarise(rows):
    """Median and quartiles of speed-up per (placement, k).

    speed-up = A* CPU / D* Lite CPU (above 1: D* Lite is faster);
    work ratio = A* expansions / D* Lite expansions.
    """
    out = []
    for placement in PLACEMENTS:
        for k in sorted({r["k"] for r in rows}):
            sel = [r for r in rows if r["placement"] == placement and r["k"] == k]
            if not sel:
                continue
            speed = sorted(r["astar_cpu_ms"] / max(r["dstar_cpu_ms"], 1e-3) for r in sel)
            work = sorted(r["astar_expanded"] / max(r["dstar_expanded"], 1) for r in sel)
            q = statistics.quantiles(speed, n=4) if len(speed) > 1 else [speed[0]] * 3
            out.append({
                "placement": placement, "k": k, "n": len(sel),
                "speedup_median": statistics.median(speed),
                "speedup_q1": q[0], "speedup_q3": q[2],
                "work_ratio_median": statistics.median(work),
                "dstar_ms_median": statistics.median(r["dstar_cpu_ms"] for r in sel),
                "astar_ms_median": statistics.median(r["astar_cpu_ms"] for r in sel),
            })
    return out


def write_csv(rows, path=CSV_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def plot(summary, path=FIG_PATH):
    """F3: speed-up of D* Lite over A* vs number of changed roads."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"anywhere": "#2a78d6", "near_vehicle": "#eb6834", "near_goal": "#1baf7a"}
    markers = {"anywhere": "o", "near_vehicle": "s", "near_goal": "^"}
    names = {"anywhere": "Anywhere on the map", "near_vehicle": "On route, near vehicle",
             "near_goal": "On route, near goal"}
    ink, quiet, grid = "#0b0b0b", "#52514e", "#e4e3df"

    fig, ax = plt.subplots(figsize=(7.2, 4.4), dpi=200)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    for placement in PLACEMENTS:
        sel = [r for r in summary if r["placement"] == placement]
        if not sel:
            continue
        ks = [r["k"] for r in sel]
        med = [r["speedup_median"] for r in sel]
        ax.fill_between(ks, [r["speedup_q1"] for r in sel], [r["speedup_q3"] for r in sel],
                        color=colors[placement], alpha=0.12, linewidth=0)
        ax.plot(ks, med, color=colors[placement], linewidth=2, marker=markers[placement],
                markersize=6, markeredgecolor="#fcfcfb", markeredgewidth=1.5,
                label=names[placement])
        # direct label at the second point, where the three lines are apart
        offset = {"anywhere": 10, "near_vehicle": 10, "near_goal": -14}[placement]
        ax.annotate(names[placement], (ks[1], med[1]), xytext=(6, offset),
                    textcoords="offset points", va="center", fontsize=8.5, color=ink)
    ax.axhline(1, color=quiet, linewidth=1, linestyle=(0, (4, 3)))
    x_right = max(r["k"] for r in summary) * 6
    ax.text(x_right, 1.12, "break-even", fontsize=8, color=quiet,
            ha="right", va="bottom")
    ax.set_xscale("log")
    ax.set_yscale("log")
    from matplotlib.ticker import FuncFormatter
    plain = FuncFormatter(lambda x, _: f"{x:g}")
    ax.xaxis.set_major_formatter(plain)
    ax.yaxis.set_major_formatter(plain)
    ax.set_xlabel("Roads changed before the replan (log scale)", fontsize=9, color=ink)
    ax.set_ylabel("Speed-up: A* CPU / D* Lite CPU (log scale)", fontsize=9, color=ink)
    best = max(r["speedup_median"] for r in summary)
    ax.set_title(f"D* Lite replans up to {best:.0f}x faster than A*, but not when the\n"
                 "route changes near the goal or hundreds of roads change",
                 fontsize=10.5, color=ink, loc="left", pad=12)
    ax.grid(True, which="major", color=grid, linewidth=0.8)
    ax.tick_params(colors=quiet, labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(grid)
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    ax.set_xlim(right=x_right)
    fig.text(0.01, 0.01, "Secunderabad graph (2,377 nodes); median over trips, band = "
             "quartiles; process_time, single thread.", fontsize=7, color=quiet)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trips", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--no-heuristic", action="store_true")
    args = parser.parse_args()
    rows = run(trips=args.trips, seed=args.seed, use_heuristic=not args.no_heuristic)
    write_csv(rows)
    summary = summarise(rows)
    plot(summary)
    print(f"{'placement':14s} {'k':>4s} {'speed-up':>9s} {'D* ms':>7s} {'A* ms':>7s} "
          f"{'work':>6s}")
    for r in summary:
        print(f"{r['placement']:14s} {r['k']:4d} {r['speedup_median']:9.2f} "
              f"{r['dstar_ms_median']:7.2f} {r['astar_ms_median']:7.2f} "
              f"{r['work_ratio_median']:6.2f}")
    print(f"wrote {CSV_PATH} and {FIG_PATH}")


if __name__ == "__main__":
    main()
