"""Plot one A* route over the Secunderabad road network (R2).

Run from the repo root:  python -m src.viz.plot_route
Saves docs/route_example.png
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                     # draw to a file, no window needed
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox

from src.search.astar import astar
from src.search.dijkstra import dijkstra
from src.search.heuristics import make_heuristic
from src.world.graph_loader import load_road_graph

OUT_FILE = Path(__file__).resolve().parents[2] / "docs" / "route_example.png"
SEED = 42
CANDIDATE_PAIRS = 300                     # try this many random pairs, keep the farthest apart


def far_apart_pair(G, seed=SEED):
    """Among random node pairs (fixed seed), return the two that are farthest apart."""
    rng = np.random.default_rng(seed)
    nodes = list(G.nodes)
    best_pair, best_dist = None, -1.0
    for _ in range(CANDIDATE_PAIRS):
        i, j = rng.choice(len(nodes), size=2, replace=False)
        a, b = G.nodes[nodes[i]], G.nodes[nodes[j]]
        dist = ox.distance.great_circle(a["lat"], a["lon"], b["lat"], b["lon"])
        if dist > best_dist:
            best_pair, best_dist = (nodes[i], nodes[j]), dist
    return best_pair, best_dist


if __name__ == "__main__":
    G = load_road_graph("secunderabad")
    (source, target), straight_m = far_apart_pair(G)

    result = astar(G, source, target, heuristic=make_heuristic(G))
    baseline = dijkstra(G, source, target)          # for the caption only
    km = sum(G[u][v][0]["length"] for u, v in zip(result.path, result.path[1:])) / 1000

    # Grey road network with the route drawn on top in one accent colour.
    fig, ax = ox.plot_graph_route(
        G, result.path, route_color="#d6336c", route_linewidth=4, route_alpha=0.9,
        orig_dest_size=0, node_size=0, edge_color="#b0b0b0", edge_linewidth=0.6,
        bgcolor="white", figsize=(8, 8), show=False, close=False,
    )
    # Label the start and end so the direction is clear without relying on colour.
    for node, label in ((source, "start"), (target, "end")):
        x, y = G.nodes[node]["x"], G.nodes[node]["y"]
        ax.scatter(x, y, s=80, c="#222222", zorder=5)
        ax.annotate(label, (x, y), xytext=(6, 6), textcoords="offset points",
                    fontsize=11, color="#222222", zorder=6)
    ax.set_title(
        f"A* route, Secunderabad: {km:.2f} km, {result.cost / 60:.1f} min free-flow\n"
        f"nodes expanded: A* {result.expanded} vs Dijkstra {baseline.expanded}",
        fontsize=11, color="#222222",
    )
    fig.savefig(OUT_FILE, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"source {source} -> target {target}, straight line {straight_m:.0f} m")
    print(f"route: {len(result.path)} nodes, {km:.2f} km, {result.cost:.1f} s")
    print(f"expanded: A* {result.expanded}, Dijkstra {baseline.expanded}")
    print(f"saved {OUT_FILE} ({OUT_FILE.stat().st_size / 1024:.0f} KB)")
