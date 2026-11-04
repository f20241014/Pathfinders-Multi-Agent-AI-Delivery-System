"""Check the FIFO property of edge travel times on a sample of edges.

FIFO ("first in, first out"): a car that enters an edge later never leaves it earlier.
With T(t) = edge travel time when entering at time t:

    t1 < t2   implies   t1 + T(t1) <= t2 + T(t2)

How we check one edge: walk through a time grid in order and keep the latest exit time
seen so far (running maximum of t1 + T(t1)). If the exit time at t2 is earlier than that,
some earlier car leaves after a later car: a violation of (running max - exit(t2)) seconds.
Only grid times are compared, so a violation shorter than the grid step can be missed;
that is why we run more than one grid step.

Run from the repo root:
    python -m src.search.fifo_check [--edges 500] [--steps 5 1] [--seed 0] [--prediction TEXT]
"""
import argparse
import math
from pathlib import Path

import numpy as np

SIM_START = 21600      # 06:00, seconds from midnight
SIM_END = 36000        # 10:00
TOL = 1e-6             # seconds; smaller differences are float rounding, not violations
DOC_PATH = Path("docs/fifo_check.md")


def check_edge(edge_time_fn, u, v, times):
    """Return (status, worst, worst_t, count) for one edge.

    status is "closed" if the edge is closed (inf) at any grid time (skipped, not checked),
    otherwise "ok". worst = largest violation in seconds (0 if none), worst_t = entry time
    of the car that was overtaken by that much (None if none),
    count = number of grid times t2 where some earlier t1 leaves later.
    """
    latest_exit = -math.inf
    worst, worst_t, count = 0.0, None, 0
    for t in times:
        T = edge_time_fn(u, v, t)
        if T == math.inf:
            return "closed", 0.0, None, 0
        exit_t = t + T
        overtaken_by = latest_exit - exit_t   # > 0: an earlier car leaves after this one
        if overtaken_by > TOL:
            count += 1
            if overtaken_by > worst:
                worst, worst_t = overtaken_by, t
        latest_exit = max(latest_exit, exit_t)
    return "ok", worst, worst_t, count


def check_fifo(edge_time_fn, edges, times):
    """Check every (u, v) in edges on the time grid; return a summary dict."""
    summary = {"edges_checked": 0, "edges_closed_skipped": 0, "edges_violating": 0,
               "violating_times": 0, "grid_times": 0,
               "worst_s": 0.0, "worst_edge": None, "worst_t": None}
    for u, v in edges:
        status, worst, worst_t, count = check_edge(edge_time_fn, u, v, times)
        if status == "closed":
            summary["edges_closed_skipped"] += 1
            continue
        summary["edges_checked"] += 1
        summary["grid_times"] += len(times)
        if count > 0:
            summary["edges_violating"] += 1
            summary["violating_times"] += count
        if worst > summary["worst_s"]:
            summary["worst_s"] = worst
            summary["worst_edge"] = (u, v)
            summary["worst_t"] = worst_t
    return summary


def sample_edges(G, n, seed):
    """n distinct (u, v) pairs from G, fixed seed."""
    pairs = sorted({(u, v) for u, v in G.edges()}, key=str)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(pairs), size=min(n, len(pairs)), replace=False)
    return [pairs[i] for i in sorted(idx)]


def percent(part, whole):
    return f"{part} / {whole} ({100 * part / whole:.2f}%)" if whole else f"{part} / 0"


def conclusion(summaries, n_edges):
    """The "## Conclusion" section, with the numbers taken from the summaries."""
    steps = list(summaries)                    # coarsest grid step first

    def share(st):                             # % of checked edges with a violation
        s = summaries[st]
        return 100 * s["edges_violating"] / s["edges_checked"] if s["edges_checked"] else 0.0

    if summaries[steps[-1]]["edges_violating"] == 0:
        return ["## Conclusion", "",
                f"No FIFO violation was found on the {n_edges}-edge sample, "
                f"even on a {steps[-1]} s grid.", ""]
    edges_text = " and ".join(
        [f"{share(steps[0]):.1f}% of edges violate FIFO on a {steps[0]} s grid"]
        + [f"{share(st):.1f}% on a {st} s grid" for st in steps[1:]])
    time_share = max(100 * s["violating_times"] / s["grid_times"]
                     for s in summaries.values() if s["grid_times"])
    time_text = "fewer than 0.1%" if time_share < 0.1 else f"up to {time_share:.1f}%"
    worst = max(s["worst_s"] for s in summaries.values())
    return [
        "## Conclusion",
        "",
        "FIFO does not hold exactly on this map with R6's traffic model. The multipliers "
        "change in 5-minute steps, so when an edge's multiplier drops at a step boundary, a "
        "car entering just after leaves before a car that entered just before. "
        f"On the {n_edges}-edge sample, {edges_text}, at {time_text} of the grid times; "
        f"the worst case is {worst:.1f} s. The counts depend on the grid step; the size of "
        "the violations is the meaningful number. Consequences: routes from "
        "time-dependent Dijkstra and A* are valid and their times are exact for the "
        "simulator (same time-fixed-at-entry rule), but they are guaranteed fastest only "
        "under FIFO. Near step boundaries a route that waits could be faster, and the "
        "searches do not consider waiting. We accept this as a documented limitation. "
        "A possible fix outside R2's scope: interpolate the multipliers between steps in "
        "traffic_model.py (R6).",
        "",
    ]


def write_doc(summaries, has_traffic, n_edges, seed, prediction, path=DOC_PATH,
              edge_time_fn=None):
    """Write the results ({grid step: summary}, coarsest first) and the FIFO assumption."""
    steps = list(summaries)

    def row(name, value):                      # one table row, one column per grid step
        return f"| {name} | " + " | ".join(value(summaries[st]) for st in steps) + " |"

    lines = []
    if not has_traffic:
        lines += ["**free-flow only (no traffic data), result is trivial and NOT valid "
                  "evidence**", ""]
    lines += [
        "# FIFO check of edge travel times (R2, Week 2)",
        "",
        f"Generated by `python -m src.search.fifo_check --edges {n_edges} "
        f"--steps {' '.join(map(str, steps))} --seed {seed}` on `World.from_defaults()`.",
        f"Traffic model active: **{'yes' if has_traffic else 'NO'}**.",
        f"Time grid: {SIM_START} to {SIM_END} s (06:00-10:00). Tolerance {TOL} s.",
        "",
        "| Grid step | " + " | ".join(f"{st} s" for st in steps) + " |",
        "| --- |" + " --- |" * len(steps),
        row("Edges sampled", lambda s: str(n_edges)),
        row("Edges checked", lambda s: str(s["edges_checked"])),
        row("Edges skipped because closed (inf)", lambda s: str(s["edges_closed_skipped"])),
        row("Edges with at least one violation",
            lambda s: percent(s["edges_violating"], s["edges_checked"])),
        row("Violating grid times (all edges)",
            lambda s: percent(s["violating_times"], s["grid_times"])),
        row("Worst violation (s)", lambda s: f"{s['worst_s']:.2f}"),
        row("Worst edge", lambda s: str(s["worst_edge"])),
        "",
        "A violation shorter than the grid step can be missed, so a finer grid finds more: "
        "the counts are lower bounds.",
        "",
    ]
    finest = summaries[steps[-1]]
    if edge_time_fn is not None and finest["worst_t"] is not None:
        (u, v), t2 = finest["worst_edge"], finest["worst_t"]
        lines += [f"Worst case on the {steps[-1]} s grid, edge {(u, v)}: the car that enters "
                  "later leaves earlier.", ""]
        for t in (t2 - steps[-1], t2):
            T = edge_time_fn(u, v, t)
            lines.append(f"- enters at {t} s: T = {T:.2f} s, leaves at {t + T:.2f} s")
        lines.append("")
    if prediction:
        lines += [f"My prediction before running: {prediction}", ""]
    lines += [
        "## The FIFO assumption",
        "",
        "With `T(t)` = travel time of an edge entered at time `t`, FIFO means "
        "`t1 < t2  =>  t1 + T(t1) <= t2 + T(t2)`: entering later never means leaving "
        "earlier. Under FIFO on every edge, arriving at a node as early as possible is "
        "always best, so time-dependent Dijkstra and A* (`src/search/time_dependent.py`, "
        "with an admissible, consistent heuristic) find the earliest arrival, and waiting "
        "at a node never helps.",
        "",
        "## What it means for the simulator",
        "",
        "The simulator fixes an edge's traversal time when the vehicle enters it "
        "(`world.edge_time(u, v, t_entry)`), exactly the cost the search uses, so the "
        "travel time the search predicts for a route is the time the simulator will "
        "produce (if nothing changes on the way). Where FIFO is violated, a vehicle could "
        "sometimes arrive earlier by waiting before entering an edge, or by reaching a "
        "node later. The searches do not consider waiting, so on those edges the route "
        "is still valid and its time still exact, but it may not be the fastest possible.",
        "",
    ]
    lines += conclusion(summaries, n_edges)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--edges", type=int, default=500)
    parser.add_argument("--steps", type=int, nargs="+", default=[5, 1],
                        help="grid steps in seconds, coarsest first")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--prediction", default="", help="written next to the result")
    args = parser.parse_args()

    from src.sim.world import World
    world = World.from_defaults()
    has_traffic = world.traffic_model is not None
    if has_traffic:
        print("Traffic model: ACTIVE (real time-varying travel times).")
    else:
        print("WARNING: no traffic model, free-flow only. Every edge is trivially FIFO; "
              "this result is NOT valid evidence.")

    edges = sample_edges(world.G, args.edges, args.seed)
    summaries = {}
    for step in args.steps:
        times = range(SIM_START, SIM_END + 1, step)
        summaries[step] = check_fifo(world.edge_time, edges, times)
        print(f"grid step {step} s: {summaries[step]}")
    write_doc(summaries, has_traffic, args.edges, args.seed, args.prediction,
              edge_time_fn=world.edge_time)
    print(f"Wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
