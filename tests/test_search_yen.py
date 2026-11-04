"""Tests for src/search/yen.py: k cheapest loopless paths, checked against networkx.

networkx is used here only as a reference answer, never inside the algorithm.
Run from the repo root:  python -m pytest tests/test_search_yen.py
"""
import math
from itertools import islice

import networkx as nx
import numpy as np
import pytest

from src.search.yen import k_shortest_paths
from src.sim.world import World

# Same tolerance as tests/test_search.py (costs are sums of floats).
TOL = 1e-6


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=TOL)


def free_flow(u, v, data):
    return data["free_flow_time"]


def reference_costs(G, source, target, k, cost_fn=free_flow):
    """networkx's k cheapest simple path costs (it needs a simple DiGraph, so keep the
    cheapest parallel road and drop blocked ones)."""
    D = nx.DiGraph()
    for u, v, data in G.edges(data=True):
        c = cost_fn(u, v, data)
        if c != math.inf and (not D.has_edge(u, v) or c < D[u][v]["w"]):
            D.add_edge(u, v, w=c)
    if source not in D or target not in D or not nx.has_path(D, source, target):
        return []
    paths = islice(nx.shortest_simple_paths(D, source, target, weight="w"), k)
    return [nx.path_weight(D, p, "w") for p in paths]


def check_paths(G, result, source, target, cost_fn=free_flow):
    """Every path simple, distinct, continuous, correctly costed; costs non-decreasing."""
    assert len({tuple(p) for p, _ in result}) == len(result)          # distinct
    for path, cost in result:
        assert path[0] == source and path[-1] == target
        assert len(set(path)) == len(path)                            # simple (no loops)
        total = 0.0
        for u, v in zip(path, path[1:]):
            assert G.has_edge(u, v)                                   # continuous
            total += min(cost_fn(u, v, d) for d in G[u][v].values())
        assert close(total, cost)
    costs = [c for _, c in result]
    assert all(a <= b + TOL for a, b in zip(costs, costs[1:]))       # non-decreasing


def random_pairs(G, count, seed):
    """`count` random (source, target) pairs of different nodes, fixed seed."""
    nodes = sorted(max(nx.strongly_connected_components(G), key=len), key=str)
    rng = np.random.default_rng(seed)
    pairs = []
    while len(pairs) < count:
        s, t = rng.choice(len(nodes), size=2, replace=False)
        pairs.append((nodes[s], nodes[t]))
    return pairs


# ---------------------------------------------------------------------------
# a) Toy graph (the same one as tests/test_search.py)
# ---------------------------------------------------------------------------
# All routes from A to E, by hand:
#   A-C-B-D-E = 2 + 1 + 5 + 2 = 10
#   A-B-D-E   = 4 + 5 + 2     = 11
#   A-C-D-E   = 2 + 8 + 2     = 12
#   A-C-E     = 2 + 10        = 12
# So there are exactly 4 loopless paths, with costs 10, 11, 12, 12.
TOY_EDGES = [("A", "B", 4), ("A", "C", 2), ("C", "B", 1), ("B", "D", 5),
             ("C", "D", 8), ("C", "E", 10), ("D", "E", 2)]


@pytest.fixture
def toy():
    G = nx.MultiDiGraph()
    for u, v, t in TOY_EDGES:
        G.add_edge(u, v, free_flow_time=t)
    return G


def test_toy_by_hand(toy):
    result = k_shortest_paths(toy, "A", "E", 3)
    assert result[0] == (["A", "C", "B", "D", "E"], 10.0)
    assert result[1] == (["A", "B", "D", "E"], 11.0)
    assert result[2][1] == 12.0
    check_paths(toy, result, "A", "E")


@pytest.mark.parametrize("k", [1, 3, 5])
def test_toy_matches_networkx(toy, k):
    result = k_shortest_paths(toy, "A", "E", k)
    assert [c for _, c in result] == pytest.approx(reference_costs(toy, "A", "E", k))
    check_paths(toy, result, "A", "E")


def test_k_larger_than_number_of_paths(toy):
    result = k_shortest_paths(toy, "A", "E", 10)
    assert [c for _, c in result] == [10.0, 11.0, 12.0, 12.0]      # only 4 exist
    check_paths(toy, result, "A", "E")


def test_unreachable_and_k_zero(toy):
    toy.add_node("island")
    assert k_shortest_paths(toy, "A", "island", 3) == []
    assert k_shortest_paths(toy, "E", "A", 3) == []                 # no road back
    assert k_shortest_paths(toy, "A", "E", 0) == []


def test_parallel_roads_count_once(toy):
    toy.add_edge("D", "E", free_flow_time=50)                      # slower parallel road
    result = k_shortest_paths(toy, "A", "E", 10)
    assert [c for _, c in result] == [10.0, 11.0, 12.0, 12.0]
    check_paths(toy, result, "A", "E")


def test_blocked_edge_is_never_used(toy):
    def cost(u, v, data):
        return math.inf if (u, v) == ("C", "B") else data["free_flow_time"]
    result = k_shortest_paths(toy, "A", "E", 5, cost_fn=cost)
    assert [c for _, c in result] == [11.0, 12.0, 12.0]
    for path, _ in result:
        assert ("C", "B") not in set(zip(path, path[1:]))


# ---------------------------------------------------------------------------
# b) Real Secunderabad graph
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def world():
    return World.from_defaults()


def test_real_graph_matches_networkx_on_50_pairs(world):
    G = world.G
    mismatches = []
    for s, t in random_pairs(G, 50, seed=20):
        expected = reference_costs(G, s, t, 5)
        for k in (1, 3, 5):
            result = k_shortest_paths(G, s, t, k)
            costs = [c for _, c in result]
            if len(costs) != len(expected[:k]) or not all(
                    close(a, b) for a, b in zip(costs, expected[:k])):
                mismatches.append((s, t, k, costs, expected[:k]))
                continue
            check_paths(G, result, s, t)
    assert mismatches == [], f"Yen and networkx disagree (s, t, k, ours, nx): {mismatches}"


def test_traffic_costs_at_8am_and_closed_road(world):
    assert world.traffic_model is not None, "traffic model must be active for this test"
    G = world.G
    s, t = random_pairs(G, 1, seed=21)[0]
    w = World(G, traffic_model=world.traffic_model)
    t_8am = 21600 + 7200
    best_path = k_shortest_paths(G, s, t, 1, cost_fn=w.cost_fn_at(t_8am))[0][0]
    u, v = best_path[len(best_path) // 2 - 1], best_path[len(best_path) // 2]
    for key in G[u][v]:                                  # close every parallel road u -> v
        w.add_disruption(u, v, key, expiry_t_seconds=math.inf)

    cost_fn = w.cost_fn_at(t_8am)
    result = k_shortest_paths(G, s, t, 5, cost_fn=cost_fn)
    assert len(result) == 5
    for path, _ in result:
        assert (u, v) not in set(zip(path, path[1:]))    # the closed road is never used
    check_paths(G, result, s, t, cost_fn)
    expected = reference_costs(G, s, t, 5, cost_fn)
    assert all(close(a, b) for a, b in zip([c for _, c in result], expected))
    # traffic at 08:00 makes the best route slower than free-flow
    assert result[0][1] > k_shortest_paths(G, s, t, 1)[0][1]
