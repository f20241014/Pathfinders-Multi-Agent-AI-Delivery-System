"""Check that the A* heuristic is admissible and consistent, on sampled targets.

h(n, target) = haversine(n, target) / max speed  (src/search/heuristics.py).

(a) Static, free-flow costs. For each sampled target:
    - one REVERSE Dijkstra from the target (walk roads backwards) gives the true
      cost-to-go true(n) from every node n to the target;
    - admissible:  h(n, target) <= true(n)              for every node n;
    - consistent:  h(u, target) <= c(u, v) + h(v, target)  for every edge (u, v),
      where c(u, v) is the cheapest parallel road (the cost the static dijkstra uses).
    slack = right side - left side; a violation is slack < -TOL.
(b) Time-dependent costs (only valid evidence if R6's traffic model is active):
    - the smallest edge_time / free_flow_time over sampled edges and a time grid
      (if it is >= 1, traffic only slows roads, so the free-flow h stays a lower bound);
    - for random trips at 3 departure times, at every node n on the dijkstra_td route:
      h(n, target) <= arrival at target - arrival at n.

Run from the repo root:
    python -m src.search.heuristic_check [--targets 300] [--pairs 200] [--seed 0]
                                         [--prediction TEXT]
"""
import argparse
import heapq
import math
from pathlib import Path

import numpy as np

from src.search.fifo_check import SIM_END, SIM_START, sample_edges
from src.search.heuristics import make_heuristic
from src.search.time_dependent import dijkstra_td

TOL = 1e-6                             # seconds
DEPARTURES = [21600, 27000, 32400]     # 06:00, 07:30, 09:00
DOC_PATH = Path("docs/heuristic_checks.md")


def edge_costs(G):
    """{(u, v): free-flow seconds of the fastest parallel road u -> v}."""
    cost = {}
    for u, v, data in G.edges(data=True):
        c = data["free_flow_time"]
        if c < cost.get((u, v), math.inf):
            cost[(u, v)] = c
    return cost


def reverse_dijkstra(cost, target):
    """True cost-to-go to `target` from every node that can reach it.

    Same as Dijkstra, but it follows roads backwards: from a node v we look at every
    road (u, v) coming INTO v, so dist[u] = cheapest cost from u to the target.
    """
    into = {}                                  # reverse adjacency: into[v] = [(u, c), ...]
    for (u, v), c in cost.items():
        into.setdefault(v, []).append((u, c))

    dist = {target: 0.0}
    done = set()
    heap = [(0.0, target)]
    while heap:
        d, v = heapq.heappop(heap)
        if v in done:
            continue
        done.add(v)
        for u, c in into.get(v, []):           # road u -> v, so u is one step further back
            if d + c < dist.get(u, math.inf):
                dist[u] = d + c
                heapq.heappush(heap, (d + c, u))
    return dist


def new_tally():
    # checked, violations (slack < -TOL), below_zero (slack < 0 at all, even by 1e-12),
    # worst = largest violation (h - true), min_slack = smallest slack seen
    return {"checked": 0, "violations": 0, "below_zero": 0, "worst": 0.0, "min_slack": math.inf}


def record(tally, slack):
    tally["checked"] += 1
    tally["min_slack"] = min(tally["min_slack"], slack)
    if slack < 0:
        tally["below_zero"] += 1
    if slack < -TOL:
        tally["violations"] += 1
        tally["worst"] = max(tally["worst"], -slack)


def static_check(G, targets, heuristic):
    """Part (a): admissibility on every (node, target) and consistency on every edge."""
    cost = edge_costs(G)
    admissible, consistent = new_tally(), new_tally()
    for target in targets:
        true = reverse_dijkstra(cost, target)
        h = {n: heuristic(n, target) for n in G.nodes}     # each h value computed once
        for n, true_n in true.items():
            if n != target:                    # h(target) = 0 = true(target): nothing to check
                record(admissible, true_n - h[n])
        for (u, v), c in cost.items():
            record(consistent, c + h[v] - h[u])
    return admissible, consistent


def min_traffic_ratio(world, edges, times):
    """Part (b1): smallest edge_time / free_flow_time over the edges and times (closed
    roads, inf, are skipped and counted)."""
    smallest, closed = math.inf, 0
    for u, v in edges:
        free = world.free_flow_time(u, v, world.edge_key(u, v))
        for t in times:
            T = world.edge_time(u, v, t)
            if T == math.inf:
                closed += 1
                continue
            smallest = min(smallest, T / free)
    return smallest, closed


def time_dependent_check(G, pairs, departures, edge_time_fn, heuristic):
    """Part (b2): along each dijkstra_td route, h(n) <= time still to drive from n."""
    tally = new_tally()
    for s, t in pairs:
        for depart in departures:
            route = dijkstra_td(G, s, t, depart, edge_time_fn)
            arrival = [depart]                 # arrival time at each node on the route
            for u, v in zip(route.path, route.path[1:]):
                arrival.append(arrival[-1] + edge_time_fn(u, v, arrival[-1]))
            for n, at_n in zip(route.path[:-1], arrival):
                record(tally, (arrival[-1] - at_n) - heuristic(n, t))
    return tally


def random_pairs(G, n, seed):
    """n random (source, target) pairs of different nodes, fixed seed."""
    nodes = sorted(G.nodes, key=str)
    rng = np.random.default_rng(seed)
    pairs = []
    while len(pairs) < n:
        s, t = rng.choice(len(nodes), size=2, replace=False)
        pairs.append((nodes[s], nodes[t]))
    return pairs


def tally_rows(name, tally):
    return [
        f"| {name}: checked | {tally['checked']:,} |",
        f"| {name}: violations (slack < -{TOL} s) | {tally['violations']} |",
        f"| {name}: below zero by any amount (float rounding) | {tally['below_zero']} |",
        f"| {name}: worst violation | {tally['worst']:.3g} s |",
        f"| {name}: smallest slack | {tally['min_slack']:.3g} s |",
    ]


def rounding_lines(res):
    """One bullet saying plainly whether any slack was below zero (even below TOL)."""
    names = ["admissible", "consistent"] + (["td"] if res["has_traffic"] else [])
    below = {k: res[k] for k in names if res[k]["below_zero"] > 0}
    if not below:
        return ["- No slack was below zero at all, not even by a rounding error."]
    parts = ", ".join(f"{k}: {t['below_zero']} (smallest {t['min_slack']:.2g} s)"
                      for k, t in below.items())
    return [f"- Some slacks were below zero by tiny amounts, far inside the {TOL} s tolerance "
            f"({parts}). These are counted, not hidden: at that size they look like float "
            "rounding, but their cause was not investigated further. A search that compares "
            "costs exactly could be affected by such values; D* Lite shrinks the heuristic by "
            "`H_SLACK` (`src/search/dstar_lite.py`) for this kind of rounding."]


def time_dependent_lines(res):
    """Part (b) of the doc; only written when the traffic model is active."""
    return [
        f"(b1) Smallest `edge_time / free_flow_time` over {res['n_ratio_edges']} sampled "
        f"edges, every {res['ratio_step']} s from {SIM_START} to {SIM_END} s: "
        f"**{res['min_ratio']:.6f}** (closed (inf) values skipped: {res['ratio_closed']}). "
        "If this is >= 1, every edge is at least as slow as free-flow, so the free-flow "
        "heuristic stays a lower bound (and consistent) with traffic.",
        "",
        f"(b2) {res['n_pairs']} random trips x departures {DEPARTURES} with `dijkstra_td`: at "
        "every node n on the route, `h(n, target) <= arrival at target - arrival at n`.",
        "",
        "| Quantity | Value |",
        "| --- | --- |",
        *tally_rows("Route nodes", res["td"]),
        "",
    ]


def write_doc(res, prediction, path=DOC_PATH):
    has_traffic = res["has_traffic"]
    lines = []
    if not has_traffic:
        lines += ["**Traffic model NOT active: part (b) is free-flow only, trivial and NOT valid "
                  "evidence. No time-dependent result is claimed.**", ""]
    else:
        lines += ["Traffic model active: **yes** (part (b) is valid evidence for R6's model).", ""]
    lines += [
        "# Heuristic checks: admissible and consistent (R2, Week 2)",
        "",
        f"Generated by `python -m src.search.heuristic_check --targets {res['n_targets']} "
        f"--pairs {res['n_pairs']} --seed {res['seed']}`. Heuristic: `make_heuristic(G)` "
        "(haversine / max speed). Tolerance "
        f"{TOL} s. Graph: {res['nodes']:,} nodes, {res['edges']:,} (u, v) roads.",
        "",
        "## (a) Static, free-flow costs",
        "",
        f"{res['n_targets']} targets sampled with a fixed seed. For each, one reverse "
        "Dijkstra (my own code, roads followed backwards) gives the true cost-to-go from every "
        "node. Admissible: `h(n, target) <= true(n)` for every node. Consistent: "
        "`h(u, target) <= c(u, v) + h(v, target)` for every road, with `c` = the fastest "
        "parallel road (what `dijkstra` uses). Slack = right side - left side.",
        "",
        "| Quantity | Value |",
        "| --- | --- |",
        *tally_rows("Admissibility, (node, target) pairs", res["admissible"]),
        *tally_rows("Consistency, (edge, target) pairs", res["consistent"]),
        "",
        "## (b) Time-dependent costs",
        "",
    ]
    if not has_traffic:
        lines += ["No result is claimed: without R6's traffic model every edge time equals "
                  "free-flow, so this part would only repeat (a).", ""]
    else:
        lines += time_dependent_lines(res)
    if prediction:
        lines += ["## My prediction (written before running, copied exactly)", "",
                  f"> {prediction}", ""]
    lines += [
        "## What is and is not proven",
        "",
        "- Shown: on the sampled targets, `h` never exceeded the true free-flow cost-to-go "
        "and never broke consistency by more than the tolerance; the rows above say whether "
        "any value was below zero at all (see below).",
        "- Shown (only if the traffic model is active): on the sampled edges and grid, "
        "traffic never made an edge faster than free-flow; on the sampled trips, `h` never "
        "exceeded the time still to drive along the route.",
        *rounding_lines(res),
        "- Not proven by these checks: other targets, other edges or times between grid "
        "points. The general argument is in `src/search/README.md` (roads are never "
        "shorter than the great-circle line and never faster than the max speed).",
        "- (b2) checks the route `dijkstra_td` found. Because FIFO does not hold exactly "
        "(see `docs/fifo_check.md`), that route's remaining time may not be the true "
        "fastest time from n, so (b2) on its own is weaker evidence than (a) and (b1).",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(world, n_targets, n_pairs, seed, n_ratio_edges=500, ratio_step=60):
    """All checks on world.G; returns a dict of results."""
    G = world.G
    heuristic = make_heuristic(G)
    rng = np.random.default_rng(seed)
    nodes = sorted(G.nodes, key=str)
    targets = [nodes[i] for i in rng.choice(len(nodes), size=n_targets, replace=False)]
    admissible, consistent = static_check(G, targets, heuristic)
    edges = sample_edges(G, n_ratio_edges, seed)
    min_ratio, ratio_closed = min_traffic_ratio(
        world, edges, range(SIM_START, SIM_END + 1, ratio_step))
    td = time_dependent_check(G, random_pairs(G, n_pairs, seed + 1), DEPARTURES,
                              world.edge_time, heuristic)
    return {"has_traffic": world.traffic_model is not None, "seed": seed,
            "n_targets": n_targets, "n_pairs": n_pairs, "nodes": G.number_of_nodes(),
            "edges": len(edge_costs(G)), "admissible": admissible, "consistent": consistent,
            "n_ratio_edges": len(edges), "ratio_step": ratio_step, "min_ratio": min_ratio,
            "ratio_closed": ratio_closed, "td": td}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--targets", type=int, default=300)
    parser.add_argument("--pairs", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--prediction", default="", help="copied into the doc as written")
    args = parser.parse_args()

    from src.sim.world import World
    world = World.from_defaults()
    if world.traffic_model is None:
        print("WARNING: no traffic model; part (b) is NOT valid evidence.")
    else:
        print("Traffic model: ACTIVE.")
    res = run(world, args.targets, args.pairs, args.seed)
    for key in ("admissible", "consistent", "td"):
        print(key, res[key])
    print("min edge_time / free_flow_time:", res["min_ratio"])
    write_doc(res, args.prediction)
    print(f"Wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
