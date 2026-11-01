"""Tests for src/search: Dijkstra, A* and the heuristic.

Run from the repo root:  python -m pytest
"""
import math

import networkx as nx
import numpy as np
import pytest

from src.search.astar import astar
from src.search.dijkstra import dijkstra
from src.search.heuristics import make_heuristic
from src.world.graph_loader import load_road_graph

# Costs are sums of floats, so compare with a tiny tolerance (a millionth of a second).
TOL = 1e-6


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=TOL)


# ---------------------------------------------------------------------------
# a) Tiny hand-made graph
# ---------------------------------------------------------------------------
#
#        4          5         2
#   A ------> B ------> D ------> E
#   |         ^         ^         ^
#   | 2       | 1       | 8       | 10
#   v         |         |         |
#   C --------+---------+---------+
#   (edges C->B = 1, C->D = 8, C->E = 10)
#
# All routes from A to E, by hand:
#   A-B-D-E   = 4 + 5 + 2      = 11
#   A-C-B-D-E = 2 + 1 + 5 + 2  = 10   <- cheapest
#   A-C-D-E   = 2 + 8 + 2      = 12
#   A-C-E     = 2 + 10         = 12
# So the expected path is A, C, B, D, E with cost 10.
#
# Hand-made heuristic to E (true costs to E are A=10, B=7, C=8, D=2, E=0;
# each guess is at most the true cost, so it is admissible).
TOY_EDGES = [("A", "B", 4), ("A", "C", 2), ("C", "B", 1), ("B", "D", 5),
             ("C", "D", 8), ("C", "E", 10), ("D", "E", 2)]
TOY_H = {"A": 6, "B": 5, "C": 6, "D": 2, "E": 0}


@pytest.fixture
def toy():
    G = nx.MultiDiGraph()
    for u, v, t in TOY_EDGES:
        G.add_edge(u, v, free_flow_time=t)
    return G


def toy_h(node, goal):
    return TOY_H[node]


def test_toy_graph_shortest_path(toy):
    for result in (dijkstra(toy, "A", "E"), astar(toy, "A", "E", heuristic=toy_h)):
        assert result.path == ["A", "C", "B", "D", "E"]
        assert result.cost == 10


def test_toy_graph_blocked_edge(toy):
    # Block C->B: the best route becomes A-B-D-E = 4 + 5 + 2 = 11.
    def block_cb(u, v, data):
        return math.inf if (u, v) == ("C", "B") else data["free_flow_time"]

    for result in (dijkstra(toy, "A", "E", block_cb),
                   astar(toy, "A", "E", block_cb, heuristic=toy_h)):
        assert result.path == ["A", "B", "D", "E"]
        assert result.cost == 11


def test_toy_graph_unreachable(toy):
    # Block every road into E: no route exists.
    def block_into_e(u, v, data):
        return math.inf if v == "E" else data["free_flow_time"]

    for result in (dijkstra(toy, "A", "E", block_into_e),
                   astar(toy, "A", "E", block_into_e, heuristic=toy_h)):
        assert result.path == []
        assert result.cost == math.inf


# ---------------------------------------------------------------------------
# Shared setup for the real graphs
# ---------------------------------------------------------------------------

def random_pairs(G, count, seed):
    """`count` random (source, target) pairs of different nodes, fixed seed."""
    rng = np.random.default_rng(seed)
    nodes = list(G.nodes)
    pairs = []
    for _ in range(count):
        i, j = rng.choice(len(nodes), size=2, replace=False)
        pairs.append((nodes[i], nodes[j]))
    return pairs


def run_all(G, pairs):
    """Run Dijkstra, A* and networkx on every pair (heuristic built once)."""
    h = make_heuristic(G)
    rows = []
    for s, t in pairs:
        rows.append({
            "pair": (s, t),
            "dijkstra": dijkstra(G, s, t),
            "astar": astar(G, s, t, heuristic=h),
            "networkx": nx.shortest_path_length(G, s, t, weight="free_flow_time"),
        })
    return rows


@pytest.fixture(scope="module")
def small():
    G = load_road_graph("secunderabad_small")
    return G, run_all(G, random_pairs(G, 200, seed=1))


@pytest.fixture(scope="module")
def full():
    G = load_road_graph("secunderabad")
    return G, run_all(G, random_pairs(G, 1000, seed=2))


def edge_cost(G, u, v):
    """Cost of the road u->v (cheapest one if there were parallel roads)."""
    return min(data["free_flow_time"] for data in G[u][v].values())


# ---------------------------------------------------------------------------
# b) and c) Costs match networkx
# ---------------------------------------------------------------------------

def check_matches_networkx(rows):
    for row in rows:
        assert close(row["dijkstra"].cost, row["networkx"]), row["pair"]
        assert close(row["astar"].cost, row["networkx"]), row["pair"]


def test_small_graph_matches_networkx(small):
    check_matches_networkx(small[1])


def test_full_graph_matches_networkx(full):
    check_matches_networkx(full[1])


# ---------------------------------------------------------------------------
# d) Routes are continuous and their cost adds up
# ---------------------------------------------------------------------------

def check_routes(G, rows):
    for row in rows:
        s, t = row["pair"]
        for result in (row["dijkstra"], row["astar"]):
            path = result.path
            assert path[0] == s and path[-1] == t
            total = 0.0
            for u, v in zip(path, path[1:]):       # every consecutive pair of nodes
                assert G.has_edge(u, v), (u, v)    # must be a real road
                total += edge_cost(G, u, v)
            assert close(total, result.cost), row["pair"]


def test_small_graph_routes_are_valid(small):
    check_routes(*small)


def test_full_graph_routes_are_valid(full):
    check_routes(*full)


# ---------------------------------------------------------------------------
# e) Blocked edges are never used
# ---------------------------------------------------------------------------

def test_blocked_edges_never_used(small):
    G, rows = small
    for row in rows[:50]:
        s, t = row["pair"]
        old_path = row["dijkstra"].path
        # Block every road on the old best route.
        blocked = set(zip(old_path, old_path[1:]))

        def cost_fn(u, v, data):
            return math.inf if (u, v) in blocked else data["free_flow_time"]

        for result in (dijkstra(G, s, t, cost_fn), astar(G, s, t, cost_fn)):
            used = set(zip(result.path, result.path[1:]))
            assert not (used & blocked), row["pair"]
            # Removing options can only make the trip the same or longer.
            assert result.cost >= row["dijkstra"].cost - TOL


# ---------------------------------------------------------------------------
# f) Heuristic is admissible (and consistent)
# ---------------------------------------------------------------------------

def test_heuristic_is_admissible(full):
    G, _ = full
    h = make_heuristic(G)
    reverse = G.reverse(copy=False)
    rng = np.random.default_rng(3)
    nodes = list(G.nodes)
    for i in rng.choice(len(nodes), size=30, replace=False):
        goal = nodes[i]
        # True cost from every node to the goal (search backwards from the goal).
        true_cost = nx.single_source_dijkstra_path_length(reverse, goal, weight="free_flow_time")
        for n, cost in true_cost.items():
            assert h(n, goal) <= cost + TOL, (n, goal)


def test_heuristic_is_consistent(full):
    # h(u) <= cost(u, v) + h(v) on every edge, for a few goals.
    G, _ = full
    h = make_heuristic(G)
    for goal in list(G.nodes)[:5]:
        for u, v, data in G.edges(data=True):
            assert h(u, goal) <= data["free_flow_time"] + h(v, goal) + TOL, (u, v, goal)


# ---------------------------------------------------------------------------
# g) A* never expands more nodes than Dijkstra
# ---------------------------------------------------------------------------

def check_expansions(rows, label):
    d = [row["dijkstra"].expanded for row in rows]
    a = [row["astar"].expanded for row in rows]
    ratios = [di / ai for di, ai in zip(d, a)]       # per pair: how many times fewer
    best, worst = int(np.argmax(ratios)), int(np.argmin(ratios))
    print(f"\n{label}: average expanded  Dijkstra {np.mean(d):.1f}  A* {np.mean(a):.1f}")
    print(f"  ratio of averages {np.mean(d) / np.mean(a):.2f}x, "
          f"average per-pair ratio {np.mean(ratios):.2f}x")
    print(f"  best pair  {rows[best]['pair']}: Dijkstra {d[best]}, A* {a[best]} ({ratios[best]:.1f}x)")
    print(f"  worst pair {rows[worst]['pair']}: Dijkstra {d[worst]}, A* {a[worst]} ({ratios[worst]:.2f}x)")
    violations = [(row["pair"], row["astar"].expanded, row["dijkstra"].expanded)
                  for row in rows if row["astar"].expanded > row["dijkstra"].expanded]
    assert not violations, f"A* expanded more than Dijkstra on: {violations}"


def test_astar_expands_no_more_small(small):
    check_expansions(small[1], "small graph, 200 pairs")


def test_astar_expands_no_more_full(full):
    check_expansions(full[1], "full graph, 1000 pairs")
