"""Tests for src/search/travel_matrix.py.

Run from the repo root:  python -m pytest tests/test_travel_matrix.py
"""
import math

import networkx as nx
import numpy as np
import pytest

from src.search.dijkstra import free_flow_cost
from src.search.travel_matrix import TravelTimeMatrix, single_source_costs
from src.world.graph_loader import load_road_graph


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)


def free_flow_factory(t):
    return free_flow_cost


def toy_graph():
    """A -> B 1, B -> A 5, B -> C 2, A -> C 10, D isolated (cannot be reached or left)."""
    G = nx.MultiDiGraph()
    for u, v, w in [("A", "B", 1), ("B", "A", 5), ("B", "C", 2), ("A", "C", 10)]:
        G.add_edge(u, v, free_flow_time=w)
    G.add_node("D")
    return G


@pytest.fixture(scope="module")
def small():
    G = load_road_graph("secunderabad_small")
    rng = np.random.default_rng(7)
    nodes = [list(G.nodes)[i] for i in rng.choice(len(G), size=20, replace=False)]
    return G, nodes


def test_matches_networkx_on_small_graph(small):
    G, nodes = small
    matrix = TravelTimeMatrix(G, free_flow_factory).travel_time_matrix(nodes, t=0)
    for i, s in enumerate(nodes):
        expected = nx.single_source_dijkstra_path_length(G, s, weight="free_flow_time")
        for j, d in enumerate(nodes):
            assert close(matrix[i][j], expected.get(d, math.inf))


def test_full_run_matches_networkx_for_every_node(small):
    G, nodes = small
    costs = single_source_costs(G, nodes[0], free_flow_cost)
    expected = nx.single_source_dijkstra_path_length(G, nodes[0], weight="free_flow_time")
    assert set(costs) == set(G.nodes)
    for n, c in costs.items():
        assert close(c, expected.get(n, math.inf))


def test_diagonal_zero_unreachable_inf_and_asymmetric():
    m = TravelTimeMatrix(toy_graph(), free_flow_factory).travel_time_matrix("ABCD", t=0)
    assert [m[i][i] for i in range(4)] == [0, 0, 0, 0]
    assert m[0][1] == 1 and m[1][0] == 5          # A->B != B->A: directed
    assert m[0][2] == 3                           # A-B-C, cheaper than A->C
    assert m[2][0] == math.inf                    # C has no way out
    assert m[0][3] == math.inf and m[3][0] == math.inf


def test_blocked_edge_changes_result_and_is_never_used():
    def factory(t):
        def cost(u, v, data):
            return math.inf if (u, v) == ("B", "C") else data["free_flow_time"]
        return cost
    m = TravelTimeMatrix(toy_graph(), factory).travel_time_matrix("ABC", t=0)
    assert m[0][2] == 10                          # A->C directly, not 3 via B->C
    assert m[1][2] == 15                          # B-A-C (5 + 10): only way round the closure
    G = toy_graph()
    G.remove_edge("B", "A")
    assert TravelTimeMatrix(G, factory).travel_time_matrix("BC", t=0)[0][1] == math.inf


def test_cache_hits_and_new_time_is_a_miss(small):
    G, nodes = small
    tm = TravelTimeMatrix(G, free_flow_factory)
    first = tm.travel_time_matrix(nodes, t=28800)
    assert (tm.hits, tm.misses) == (0, 20) and tm.expanded > 0
    expanded = tm.expanded
    assert tm.travel_time_matrix(nodes, t=28800) == first
    assert (tm.hits, tm.misses) == (20, 20) and tm.expanded == expanded
    tm.travel_time_matrix(nodes, t=30000)
    assert tm.misses == 40 and tm.expanded > expanded


def test_cost_fn_factory_gets_the_time():
    seen = []

    def factory(t):
        seen.append(t)
        return free_flow_cost
    TravelTimeMatrix(toy_graph(), factory).travel_time_matrix("AB", t=123)
    assert seen and all(t == 123 for t in seen)


def test_early_exit_same_numbers_as_full_run(small):
    G, nodes = small
    targets = nodes[1:6]
    full = single_source_costs(G, nodes[0], free_flow_cost)
    early = single_source_costs(G, nodes[0], free_flow_cost, targets=targets)
    for d in targets:
        assert early[d] == full[d]
    assert len(early) <= len(full)
