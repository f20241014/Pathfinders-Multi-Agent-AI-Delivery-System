"""Tests for src/search/time_dependent.py: dijkstra_td and astar_td.

Run from the repo root:  python -m pytest tests/test_search_time_dependent.py
"""
import math

import networkx as nx
import numpy as np
import pytest

from src.search.astar import astar
from src.search.dijkstra import dijkstra
from src.search.heuristics import make_heuristic
from src.search.time_dependent import astar_td, dijkstra_td
from src.sim.world import World

# Same tolerance as tests/test_search.py (costs are sums of floats).
TOL = 1e-6
DEPARTURES = [21600, 27000, 32400]     # 06:00, 07:30, 09:00


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=TOL)


def zero_h(node, goal):
    return 0.0


def free_flow_fn(G):
    """edge_time_fn that ignores t: free-flow time of the fastest road u -> v."""
    def fn(u, v, t):
        return min(d["free_flow_time"] for d in G[u][v].values())
    return fn


def replay(G, path, depart_t, edge_time_fn):
    """Drive the path edge by edge, each edge costed at its entry time; return seconds."""
    t = depart_t
    for u, v in zip(path, path[1:]):
        assert G.has_edge(u, v), f"route jumps from {u} to {v}"
        cost = edge_time_fn(u, v, t)
        assert cost != math.inf, f"route uses closed road {u}->{v} at t={t}"
        t += cost
    return t - depart_t


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
# a) Toy graph with a time-varying edge, checked by hand
# ---------------------------------------------------------------------------
#
#   s --10--> a --10--> t
#   s --5---> b --T(t)--> t     with T(t) = max(2, 40 - t)  (slower early on)
#
# Leave at 0:  via a: 10 + 10 = 20.   via b: enter b->t at 5, T = 35, total 40.
#              -> path s, a, t; cost 20; arrival 20.
# Leave at 40: via a: 10 + 10 = 20.   via b: enter b->t at 45, T = 2, total 7.
#              -> path s, b, t; cost 7; arrival 47.
@pytest.fixture
def toy():
    G = nx.MultiDiGraph()
    for u, v in [("s", "a"), ("a", "t"), ("s", "b"), ("b", "t")]:
        G.add_edge(u, v)
    return G


def toy_fn(u, v, t):
    if (u, v) == ("b", "t"):
        return max(2.0, 40.0 - t)
    return {("s", "a"): 10.0, ("a", "t"): 10.0, ("s", "b"): 5.0}[(u, v)]


@pytest.mark.parametrize("search", [dijkstra_td, astar_td])
def test_toy_time_varying_by_hand(toy, search):
    r = search(toy, "s", "t", 0, toy_fn, heuristic=zero_h)
    assert (r.path, r.cost, r.arrival_t) == (["s", "a", "t"], 20.0, 20.0)
    r = search(toy, "s", "t", 40, toy_fn, heuristic=zero_h)
    assert (r.path, r.cost, r.arrival_t) == (["s", "b", "t"], 7.0, 47.0)


@pytest.mark.parametrize("search", [dijkstra_td, astar_td])
def test_cost_uses_entry_time_not_departure_time(toy, search):
    # a->t is open at departure (t=0) but closed from t=5; we only reach it at t=10.
    # b->t costs 30 always. Correct answer: s, b, t with cost 35 (not s, a, t with 20).
    def fn(u, v, t):
        if (u, v) == ("a", "t"):
            return math.inf if t >= 5 else 10.0
        if (u, v) == ("b", "t"):
            return 30.0
        return toy_fn(u, v, t)
    r = search(toy, "s", "t", 0, fn, heuristic=zero_h)
    assert (r.path, r.cost, r.arrival_t) == (["s", "b", "t"], 35.0, 35.0)


@pytest.mark.parametrize("search", [dijkstra_td, astar_td])
def test_unreachable(toy, search):
    toy.add_node("island")
    r = search(toy, "s", "island", 0, toy_fn, heuristic=zero_h)
    assert r.path == [] and r.cost == math.inf and r.arrival_t == math.inf

    def all_closed(u, v, t):
        return math.inf
    r = search(toy, "s", "t", 0, all_closed, heuristic=zero_h)
    assert r.path == [] and r.cost == math.inf


@pytest.mark.parametrize("search", [dijkstra_td, astar_td])
def test_source_equals_target(toy, search):
    r = search(toy, "s", "s", 100, toy_fn, heuristic=zero_h)
    assert (r.path, r.cost, r.arrival_t) == (["s"], 0.0, 100.0)


# ---------------------------------------------------------------------------
# b) Real Secunderabad graph with World.from_defaults()
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def world():
    return World.from_defaults()


@pytest.fixture(scope="module")
def h(world):
    return make_heuristic(world.G)


def test_constant_free_flow_matches_static_versions(world, h):
    G = world.G
    fn = free_flow_fn(G)
    for s, t in random_pairs(G, 50, seed=10):
        static_d, static_a = dijkstra(G, s, t), astar(G, s, t, heuristic=h)
        td_d = dijkstra_td(G, s, t, 21600, fn)
        td_a = astar_td(G, s, t, 21600, fn, heuristic=h)
        assert close(td_d.cost, static_d.cost) and close(td_a.cost, static_a.cost)
        assert close(td_d.arrival_t, 21600 + td_d.cost)


def test_astar_td_equals_dijkstra_td_on_200_pairs(world, h):
    """With real traffic, A* and Dijkstra must agree on every pair and departure time.

    If this ever fails, the message lists the pairs: do NOT loosen the test (it may mean
    FIFO is violated or the heuristic overestimates).
    """
    G = world.G
    mismatches = []
    for s, t in random_pairs(G, 200, seed=11):
        for depart in DEPARTURES:
            d = dijkstra_td(G, s, t, depart, world.edge_time)
            a = astar_td(G, s, t, depart, world.edge_time, heuristic=h)
            if not close(a.cost, d.cost):
                mismatches.append((s, t, depart, d.cost, a.cost))
                continue
            assert close(replay(G, d.path, depart, world.edge_time), d.cost)
            assert close(replay(G, a.path, depart, world.edge_time), a.cost)
            assert d.path[0] == s and d.path[-1] == t
    assert mismatches == [], f"A* and Dijkstra disagree (s, t, depart, dij, astar): {mismatches}"


def test_default_heuristic_is_used(world, h):
    G = world.G
    s, t = random_pairs(G, 1, seed=12)[0]
    with_default = astar_td(G, s, t, 27000, world.edge_time)
    with_given = astar_td(G, s, t, 27000, world.edge_time, heuristic=h)
    assert with_default == with_given


def test_closed_roads_are_never_used(world, h):
    G = world.G
    for s, t in random_pairs(G, 20, seed=13):
        open_world = World(G, traffic_model=world.traffic_model)
        before = dijkstra_td(G, s, t, 27000, open_world.edge_time)
        if len(before.path) < 3:
            continue
        mid = len(before.path) // 2
        u, v = before.path[mid - 1], before.path[mid]

        closed_world = World(G, traffic_model=world.traffic_model)
        for key in G[u][v]:                       # close every parallel road u -> v
            closed_world.add_disruption(u, v, key, expiry_t_seconds=math.inf)
        for search in (dijkstra_td, astar_td):
            after = search(G, s, t, 27000, closed_world.edge_time, heuristic=h)
            used = set(zip(after.path, after.path[1:]))
            assert (u, v) not in used
            if after.path:                        # a detour can only be slower
                assert after.cost >= before.cost - TOL
                assert close(replay(G, after.path, 27000, closed_world.edge_time), after.cost)
