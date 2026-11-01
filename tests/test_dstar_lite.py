"""Tests for src/search/dstar_lite.py (R7, Week 1).

Week 1 goal from the plan: implement D* Lite on a tiny grid and unit test
that its path cost equals A*. The A* reference is R2's from-scratch
src/search/astar.py, so both planners are checked against each other.

Run from the repo root:  python -m pytest tests/test_dstar_lite.py
"""
import math
import random

import networkx as nx
import pytest

from src.search.astar import astar
from src.search.dstar_lite import DStarLite

# Costs are sums of floats, so compare with a tiny tolerance.
TOL = 1e-6


def close(a, b):
    if math.isinf(a) or math.isinf(b):
        return a == b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=TOL)


def to_adjacency(G):
    """networkx graph -> {u: {v: cost}} for DStarLite.

    Every node becomes a key (also dead ends), and parallel edges keep the
    cheapest one, the same rule graph_loader uses.
    """
    adj = {u: {} for u in G.nodes}
    for u, v, data in G.edges(data=True):
        t = data["free_flow_time"]
        adj[u][v] = min(t, adj[u].get(v, math.inf))
    return adj


def zero_h(node, goal):
    """Admissible for any non-negative costs (A* then behaves like Dijkstra)."""
    return 0.0


def astar_cost(G, s, t):
    return astar(G, s, t, heuristic=zero_h).cost


def path_is_valid(G, path, s, t):
    return path[0] == s and path[-1] == t and all(G.has_edge(u, v) for u, v in zip(path, path[1:]))


def grid(rows, cols, weights=None):
    """Tiny two-way grid. Node (r, c); every road is a pair of directed edges."""
    G = nx.DiGraph()
    rnd = random.Random(0)
    for r in range(rows):
        for c in range(cols):
            for dr, dc in ((0, 1), (1, 0)):
                r2, c2 = r + dr, c + dc
                if r2 < rows and c2 < cols:
                    w = weights(rnd) if weights else 1.0
                    G.add_edge((r, c), (r2, c2), free_flow_time=w)
                    G.add_edge((r2, c2), (r, c), free_flow_time=w)
    return G


# ---------------------------------------------------------------------------
# a) R2's hand-checked toy graph (best route A-C-B-D-E, cost 10)
# ---------------------------------------------------------------------------
TOY_EDGES = [("A", "B", 4), ("A", "C", 2), ("C", "B", 1), ("B", "D", 5),
             ("C", "D", 8), ("C", "E", 10), ("D", "E", 2)]


@pytest.fixture
def toy():
    G = nx.DiGraph()
    for u, v, t in TOY_EDGES:
        G.add_edge(u, v, free_flow_time=t)
    return G


def test_toy_graph_matches_hand_answer_and_astar(toy):
    d = DStarLite(to_adjacency(toy), "A", "E")
    assert d.get_path() == ["A", "C", "B", "D", "E"]
    assert d.path_cost() == 10
    assert close(d.path_cost(), astar_cost(toy, "A", "E"))


def test_toy_graph_cost_change_replans(toy):
    # Make C->B expensive: best route becomes A-B-D-E = 11.
    d = DStarLite(to_adjacency(toy), "A", "E")
    d.get_path()
    d.update_edge_cost("C", "B", 100)
    toy["C"]["B"]["free_flow_time"] = 100
    assert d.get_path() == ["A", "B", "D", "E"]
    assert d.path_cost() == 11
    assert close(d.path_cost(), astar_cost(toy, "A", "E"))


# ---------------------------------------------------------------------------
# b) Tiny grids (the Week 1 task)
# ---------------------------------------------------------------------------
def test_unit_grid_cost_equals_astar():
    G = grid(3, 3)
    d = DStarLite(to_adjacency(G), (0, 0), (2, 2))
    path = d.get_path()
    assert path_is_valid(G, path, (0, 0), (2, 2))
    assert d.path_cost() == 4                      # Manhattan distance on a unit grid
    assert close(d.path_cost(), astar_cost(G, (0, 0), (2, 2)))


def test_weighted_grid_cost_equals_astar_for_all_pairs():
    G = grid(4, 4, weights=lambda rnd: rnd.randint(1, 9))
    nodes = list(G.nodes)
    for s in nodes:
        for t in nodes:
            d = DStarLite(to_adjacency(G), s, t)
            path = d.get_path()
            assert path_is_valid(G, path, s, t)
            assert close(d.path_cost(), astar_cost(G, s, t)), (s, t)


def test_grid_reroutes_around_expensive_road():
    # 3x3 unit grid, start (0,0), goal (0,2). Direct route along row 0 costs 2.
    G = grid(3, 3)
    d = DStarLite(to_adjacency(G), (0, 0), (0, 2))
    assert d.path_cost() == 2
    # Make the middle of row 0 very slow in both directions.
    for u, v in (((0, 1), (0, 2)), ((0, 2), (0, 1))):
        d.update_edge_cost(u, v, 50)
        G[u][v]["free_flow_time"] = 50
    path = d.get_path()
    assert ((0, 1), (0, 2)) not in list(zip(path, path[1:]))
    assert d.path_cost() == 4                      # detour through row 1
    assert close(d.path_cost(), astar_cost(G, (0, 0), (0, 2)))


def test_moving_start_keeps_costs_equal_to_astar():
    G = grid(4, 4, weights=lambda rnd: rnd.randint(1, 9))
    goal = (3, 3)
    d = DStarLite(to_adjacency(G), (0, 0), goal)
    rnd = random.Random(1)
    while d.start != goal:
        # Change one random road, then drive one step along the current path.
        u, v = rnd.choice(list(G.edges))
        w = rnd.randint(1, 9)
        d.update_edge_cost(u, v, w)
        G[u][v]["free_flow_time"] = w
        assert close(d.path_cost(), astar_cost(G, d.start, goal))
        d.move_start(d.get_path()[1])


# ---------------------------------------------------------------------------
# c) Unreachable goal and bad input
# ---------------------------------------------------------------------------
def test_unreachable_goal_returns_empty_path():
    G = nx.DiGraph()
    G.add_edge("A", "B", free_flow_time=1)
    G.add_edge("C", "B", free_flow_time=1)        # C can reach B, nothing reaches C
    d = DStarLite(to_adjacency(G), "A", "C")
    assert d.get_path() == []
    assert d.path_cost() == math.inf
    assert astar_cost(G, "A", "C") == math.inf


def test_unknown_nodes_and_edges_raise():
    adj = {"A": {"B": 1.0}, "B": {}}
    with pytest.raises(KeyError):
        DStarLite(adj, "A", "Z")
    d = DStarLite(adj, "A", "B")
    with pytest.raises(KeyError):
        d.update_edge_cost("B", "A", 1.0)
    with pytest.raises(ValueError):
        d.update_edge_cost("A", "B", -1.0)


# ---------------------------------------------------------------------------
# d) Random cost changes (small version of the Week 2 property test)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(100))
def test_random_cost_changes_match_fresh_astar(seed):
    rnd = random.Random(seed)
    G = grid(rnd.randint(2, 5), rnd.randint(2, 5), weights=lambda r: r.randint(1, 9))
    nodes = list(G.nodes)
    s, t = rnd.sample(nodes, 2)
    d = DStarLite(to_adjacency(G), s, t)
    for _ in range(10):
        u, v = rnd.choice(list(G.edges))
        w = rnd.randint(1, 20)
        d.update_edge_cost(u, v, w)
        G[u][v]["free_flow_time"] = w
        assert close(d.path_cost(), astar_cost(G, s, t))
