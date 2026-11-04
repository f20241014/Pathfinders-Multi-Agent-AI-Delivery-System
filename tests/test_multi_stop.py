"""Tests for src/search/multi_stop.py (R7, Week 3): one D* Lite per leg.

Every route is checked against R2's A* run leg by leg from scratch.
"""
import math
import random

import networkx as nx
import pytest

from src.search.astar import astar
from src.search.multi_stop import MultiStopPlanner, route_cost


def close(a, b):
    if math.isinf(a) or math.isinf(b):
        return a == b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)


def grid(rows, cols, seed=0):
    rnd = random.Random(seed)
    G = nx.DiGraph()
    for r in range(rows):
        for c in range(cols):
            for dr, dc in ((0, 1), (1, 0)):
                r2, c2 = r + dr, c + dc
                if r2 < rows and c2 < cols:
                    w = rnd.randint(1, 9)
                    G.add_edge((r, c), (r2, c2), free_flow_time=w)
                    G.add_edge((r2, c2), (r, c), free_flow_time=w)
    return G


def zero_h(a, b):
    return 0.0


def astar_route_cost(G, start, stops):
    """Reference: sum of fresh A* costs leg by leg."""
    total, here = 0.0, start
    for stop in stops:
        c = astar(G, here, stop, heuristic=zero_h).cost
        if c == math.inf:
            return math.inf
        total += c
        here = stop
    return total


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------
def test_three_stops_on_a_line():
    G = nx.DiGraph()
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        G.add_edge(a, b, free_flow_time=1)
        G.add_edge(b, a, free_flow_time=1)
    p = MultiStopPlanner.from_networkx(G, "A", ["C", "B", "D"])
    assert p.path() == ["A", "B", "C", "B", "C", "D"]
    assert p.path_cost() == 5
    assert p.remaining_stops == ["C", "B", "D"]


def test_route_visits_stops_in_order_and_matches_astar():
    G = grid(5, 5)
    stops = [(4, 0), (0, 4), (4, 4), (2, 2)]
    p = MultiStopPlanner.from_networkx(G, (0, 0), stops)
    path = p.path()
    # stops appear in order
    i = 0
    for stop in stops:
        i = path.index(stop, i)
    assert close(p.path_cost(), astar_route_cost(G, (0, 0), stops))
    assert close(route_cost(p.legs[0].graph, path), p.path_cost())


def test_start_or_repeated_stop_is_skipped():
    G = grid(3, 3)
    p = MultiStopPlanner.from_networkx(G, (0, 0), [(0, 0), (2, 2), (2, 2)])
    assert p.remaining_stops == [(2, 2), (2, 2)]
    assert close(p.path_cost(), astar_route_cost(G, (0, 0), [(2, 2)]))


def test_no_stops():
    p = MultiStopPlanner.from_networkx(grid(2, 2), (0, 0), [])
    assert p.done
    assert p.path() == [(0, 0)]
    assert p.path_cost() == 0


# ---------------------------------------------------------------------------
# Driving: legs advance when a stop is reached
# ---------------------------------------------------------------------------
def test_driving_the_route_advances_legs():
    G = grid(4, 4)
    stops = [(3, 0), (0, 3), (3, 3)]
    p = MultiStopPlanner.from_networkx(G, (0, 0), stops)
    visited = []
    while not p.done:
        nxt = p.path()[1]
        p.move_start(nxt)
        if nxt in stops:
            visited.append(nxt)
    assert visited[:3] == stops
    assert p.current_goal is None


def test_change_on_a_later_leg_is_seen_before_reaching_it():
    G = grid(4, 4)
    stops = [(0, 3), (3, 3)]
    p = MultiStopPlanner.from_networkx(G, (0, 0), stops)
    later = p.leg_paths()[1]
    u, v = later[0], later[1]           # first road of leg 2
    p.close_edge(u, v)
    G[u][v]["free_flow_time"] = math.inf
    assert (u, v) not in list(zip(p.path(), p.path()[1:]))
    assert close(p.path_cost(), astar_route_cost(G, (0, 0), stops))


def test_unreachable_stop_is_reported():
    G = grid(3, 3)
    p = MultiStopPlanner.from_networkx(G, (0, 0), [(2, 2), (0, 2)])
    for u in G.predecessors((0, 2)):
        p.close_edge(u, (0, 2))
    assert p.unreachable_stops() == [(0, 2)]
    assert p.path() == []
    assert p.path_cost() == math.inf


# ---------------------------------------------------------------------------
# Property test: random changes while driving, every step vs A* per leg
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(60))
def test_random_changes_while_driving_match_astar(seed):
    rnd = random.Random(seed)
    G = grid(rnd.randint(3, 6), rnd.randint(3, 6), seed)
    nodes = list(G.nodes)
    start = rnd.choice(nodes)
    stops = [rnd.choice(nodes) for _ in range(rnd.randint(1, 4))]
    h = manhattan if seed % 2 else None
    p = MultiStopPlanner.from_networkx(G, start, stops, heuristic=h)
    closed = set()
    for _ in range(25):
        u, v = rnd.choice(list(G.edges))
        if rnd.random() < 0.25:
            p.close_edge(u, v)
            G[u][v]["free_flow_time"] = math.inf
            closed.add((u, v))
        elif (u, v) in closed and rnd.random() < 0.5:
            p.reopen_edge(u, v, 5)
            G[u][v]["free_flow_time"] = 5
            closed.discard((u, v))
        else:
            w = rnd.randint(1, 20)
            p.update_edge_cost(u, v, w)
            G[u][v]["free_flow_time"] = w
            closed.discard((u, v))
            for leg in p.legs:
                leg.closed.pop((u, v), None)
        expected = astar_route_cost(G, p.position, p.remaining_stops)
        assert close(p.path_cost(), expected)
        path = p.path()
        if len(path) > 1 and rnd.random() < 0.5:
            p.move_start(path[1])


def test_real_map_three_stops_with_closure():
    from src.search.heuristics import make_heuristic
    from src.world.graph_loader import load_road_graph
    G = load_road_graph("secunderabad_small")
    h = make_heuristic(G)
    rnd = random.Random(3)
    nodes = sorted(G.nodes)
    for _ in range(50):
        start, *stops = rnd.sample(nodes, 4)
        ref = 0.0
        here = start
        for s in stops:
            ref += astar(G, here, s).cost
            here = s
        if ref < math.inf:
            break
    p = MultiStopPlanner.from_networkx(G, start, stops, heuristic=h)
    assert close(p.path_cost(), ref)
    u, v = p.path()[0], p.path()[1]
    p.close_edge(u, v)

    def blocked(a, b, data):
        return math.inf if (a, b) == (u, v) else data["free_flow_time"]
    ref2, here = 0.0, start
    for s in stops:
        ref2 += astar(G, here, s, blocked).cost
        here = s
    assert close(p.path_cost(), ref2)
