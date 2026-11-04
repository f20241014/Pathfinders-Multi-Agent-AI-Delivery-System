"""Benchmark: static Dijkstra vs A* on random origin-destination (OD) pairs (figure F2).

For each pair we run both searches with free-flow costs and record the number of nodes
expanded and the run time (time.perf_counter). Both must return the same cost.

Run from the repo root:
    python -m src.search.benchmark [--pairs 200] [--seed 42] [--prediction TEXT]
Writes docs/benchmark_dijkstra_astar.md, docs/benchmark_dijkstra_astar.csv and
reports/figures/F2_astar_vs_dijkstra.png.
"""
import argparse
import csv
import math
import platform
import time
from pathlib import Path

import networkx as nx
import numpy as np

from src.search.astar import astar
from src.search.dijkstra import dijkstra
from src.search.heuristics import make_heuristic

MD_PATH = Path("docs/benchmark_dijkstra_astar.md")
CSV_PATH = Path("docs/benchmark_dijkstra_astar.csv")
FIG_PATH = Path("reports/figures/F2_astar_vs_dijkstra.png")
WARMUP_PAIRS = 5
MEASURED_HEADER = "## Where A*'s time goes (measured)"


def same_cost(a, b):
    """Same tolerance as tests/test_search.py (costs are sums of floats)."""
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)


def random_od_pairs(G, n, seed):
    """n random (source, target) pairs of different nodes from the largest strongly
    connected component (so every target is reachable), fixed seed."""
    nodes = sorted(max(nx.strongly_connected_components(G), key=len), key=str)
    rng = np.random.default_rng(seed)
    pairs = []
    while len(pairs) < n:
        s, t = rng.choice(len(nodes), size=2, replace=False)
        pairs.append((nodes[s], nodes[t]))
    return pairs


def timed(search, *args, **kwargs):
    """Run one search; return (result, milliseconds)."""
    start = time.perf_counter()
    result = search(*args, **kwargs)
    return result, (time.perf_counter() - start) * 1000


def run_benchmark(G, pairs):
    """One row per pair: expansions, run times and costs of both searches."""
    h = make_heuristic(G)                     # built once, outside the timed part
    for s, t in pairs[:WARMUP_PAIRS]:         # warm-up runs (not recorded): caches, imports
        dijkstra(G, s, t)
        astar(G, s, t, heuristic=h)

    rows = []
    for i, (s, t) in enumerate(pairs):
        d, d_ms = timed(dijkstra, G, s, t)
        a, a_ms = timed(astar, G, s, t, heuristic=h)
        if not same_cost(d.cost, a.cost):
            raise AssertionError(f"pair {i} ({s} -> {t}): Dijkstra {d.cost} != A* {a.cost}")
        rows.append({"pair": i, "source": s, "target": t,
                     "dijkstra_cost_s": d.cost, "astar_cost_s": a.cost,
                     "dijkstra_expanded": d.expanded, "astar_expanded": a.expanded,
                     "dijkstra_ms": d_ms, "astar_ms": a_ms})
    return rows


def stats(values):
    """Mean, median and 95th percentile of a list of numbers."""
    return {"mean": float(np.mean(values)), "median": float(np.median(values)),
            "p95": float(np.percentile(values, 95))}


def summarise(rows):
    """Stats for both searches, Dijkstra / A* ratios, and pairs where A* expanded more."""
    out = {}
    for measure in ("expanded", "ms"):
        d = stats([r[f"dijkstra_{measure}"] for r in rows])
        a = stats([r[f"astar_{measure}"] for r in rows])
        ratio = {k: d[k] / a[k] for k in d}
        per_pair = [r[f"dijkstra_{measure}"] / r[f"astar_{measure}"] for r in rows]
        out[measure] = {"dijkstra": d, "astar": a, "ratio": ratio,
                        "median_per_pair_ratio": float(np.median(per_pair))}
    out["astar_expanded_more"] = sum(r["astar_expanded"] > r["dijkstra_expanded"] for r in rows)
    out["pairs"] = len(rows)
    return out


def write_csv(rows, path=CSV_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path=CSV_PATH):
    """Rows saved by write_csv, with numbers turned back into numbers (no re-timing)."""
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for name in r:
            if name.endswith(("_expanded", "pair")):
                r[name] = int(r[name])
            elif name.endswith(("_s", "_ms")):
                r[name] = float(r[name])
    return rows


def saved_prediction(path=MD_PATH):
    """The prediction already written in the doc (the "> ..." line under its heading)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index("## My prediction (written before running, copied exactly)")
    return next(line[2:] for line in lines[start:] if line.startswith("> "))


def write_markdown(summary, prediction, seed, path=MD_PATH):
    """Write the benchmark doc. A "Where A*'s time goes" section already in the file
    (written by src/search/heuristic_cost.py) is kept at the end."""
    e, m = summary["expanded"], summary["ms"]

    def row(name, part, fmt):
        return (f"| {name} | " + " | ".join(fmt.format(part[k]) for k in ("mean", "median", "p95"))
                + " |")

    lines = [
        "# Dijkstra vs A* benchmark (R2, Week 2, figure F2)",
        "",
        f"Generated by `python -m src.search.benchmark --pairs {summary['pairs']} --seed {seed}`;",
        "the doc can be rebuilt from the saved CSV without re-timing with "
        "`python -m src.search.benchmark --from-csv`.",
        f"{summary['pairs']} random OD pairs from the largest strongly connected component of "
        "the Secunderabad graph, free-flow costs, my static `dijkstra` and `astar` "
        "(haversine / max speed heuristic, built once before timing). "
        f"{WARMUP_PAIRS} warm-up pairs first (not recorded). Both searches gave the same cost "
        "on every pair (tolerance 1e-9 relative, 1e-6 s absolute).",
        f"Machine: {platform.platform()}, Python {platform.python_version()}. Run times are "
        "single runs measured with `time.perf_counter()` and differ between machines.",
        "",
        "## Nodes expanded",
        "",
        "| | Mean | Median | 95th percentile |",
        "| --- | --- | --- | --- |",
        row("Dijkstra", e["dijkstra"], "{:.0f}"),
        row("A*", e["astar"], "{:.0f}"),
        "",
        f"Pairs where A* expanded more nodes than Dijkstra: {summary['astar_expanded_more']} "
        f"of {summary['pairs']}.",
        "",
        "## Run time (ms)",
        "",
        "| | Mean | Median | 95th percentile |",
        "| --- | --- | --- | --- |",
        row("Dijkstra", m["dijkstra"], "{:.2f}"),
        row("A*", m["astar"], "{:.2f}"),
        "",
        "## Ratios, Dijkstra / A*",
        "",
        "The first two rows are the headline numbers. The last two divide a statistic of "
        "Dijkstra's trips by the same statistic of A*'s trips; the median (or 95th "
        "percentile) trip is not the same trip for both, so they compare different trips "
        "and are shown for reference only.",
        "",
        "| Ratio | Nodes expanded | Run time |",
        "| --- | --- | --- |",
        f"| Ratio of means (headline) | {e['ratio']['mean']:.2f} | {m['ratio']['mean']:.2f} |",
        f"| Median of the per-pair ratio (headline) | {e['median_per_pair_ratio']:.2f} | "
        f"{m['median_per_pair_ratio']:.2f} |",
        f"| Ratio of the medians (different trips) | {e['ratio']['median']:.2f} | "
        f"{m['ratio']['median']:.2f} |",
        f"| Ratio of the 95th percentiles (different trips) | {e['ratio']['p95']:.2f} | "
        f"{m['ratio']['p95']:.2f} |",
        "",
        "## My prediction (written before running, copied exactly)",
        "",
        f"> {prediction}" if prediction else "> (none given)",
        "",
        "Measured, Dijkstra / A*: nodes expanded **"
        f"{e['ratio']['mean']:.2f}x** (ratio of means), "
        f"{e['median_per_pair_ratio']:.2f}x (median per-pair ratio); run time **"
        f"{m['ratio']['mean']:.2f}x** (ratio of means), "
        f"{m['median_per_pair_ratio']:.2f}x (median per-pair ratio).",
        "",
        f"Per-pair data: `{CSV_PATH.as_posix()}`. Figure: `{FIG_PATH.as_posix()}`.",
        "",
    ]
    kept = ""                                 # keep heuristic_cost.py's section, if any
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if MEASURED_HEADER in old:
            kept = "\n" + old[old.index(MEASURED_HEADER):]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + kept, encoding="utf-8")


def plot(rows, path=FIG_PATH):
    """Two scatter plots, one dot per pair: Dijkstra (x) vs A* (y). Below the grey
    'equal' line, A* did less work."""
    import matplotlib
    matplotlib.use("Agg")                     # draw to a file, no window
    import matplotlib.pyplot as plt

    blue, ink, muted = "#2a78d6", "#0b0b0b", "#52514e"   # one series: one colour
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6), facecolor="#fcfcfb")
    panels = [("expanded", "Nodes expanded"), ("ms", "Run time (ms)")]
    for ax, (measure, title) in zip(axes, panels):
        x = [r[f"dijkstra_{measure}"] for r in rows]
        y = [r[f"astar_{measure}"] for r in rows]
        top = max(max(x), max(y)) * 1.05
        ax.plot([0, top], [0, top], color=muted, linewidth=1, linestyle="--")
        ax.text(top * 0.97, top * 0.90, "equal", color=muted, ha="right", fontsize=9)
        ax.scatter(x, y, s=22, color=blue, alpha=0.75, edgecolors="#fcfcfb", linewidths=0.8)
        ax.set_xlim(0, top)
        ax.set_ylim(0, top)
        ax.set_title(title, color=ink, fontsize=11, loc="left")
        ax.set_xlabel("Dijkstra", color=muted)
        ax.set_ylabel("A*", color=muted)
        ax.set_facecolor("#fcfcfb")
        ax.grid(color="#e6e5e0", linewidth=0.6)
        ax.tick_params(colors=muted, labelsize=9)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#c9c8c2")
    fig.suptitle(f"A* vs Dijkstra on {len(rows)} OD pairs (one dot per pair)",
                 color=ink, fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pairs", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--prediction", default="", help="copied into the doc as written")
    parser.add_argument("--from-csv", action="store_true",
                        help="rebuild the doc from the saved CSV (no timing, no new figure); "
                             "keeps the prediction already in the doc")
    args = parser.parse_args()

    if args.from_csv:
        rows = read_csv()
        prediction = args.prediction or saved_prediction()
        write_markdown(summarise(rows), prediction, args.seed)
        print(f"Rebuilt {MD_PATH} from {CSV_PATH} ({len(rows)} pairs, nothing re-timed)")
        return

    from src.world.graph_loader import load_road_graph
    G = load_road_graph("secunderabad")
    rows = run_benchmark(G, random_od_pairs(G, args.pairs, args.seed))
    summary = summarise(rows)
    write_csv(rows)
    write_markdown(summary, args.prediction, args.seed)
    plot(rows)
    for measure in ("expanded", "ms"):
        print(measure, summary[measure])
    print("A* expanded more on", summary["astar_expanded_more"], "pairs")
    print(f"Wrote {MD_PATH}, {CSV_PATH}, {FIG_PATH}")


if __name__ == "__main__":
    main()
