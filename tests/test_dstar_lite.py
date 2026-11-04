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


# ---------------------------------------------------------------------------
# e) Road closures (R2 review on PR #5)
# ---------------------------------------------------------------------------
def test_closure_on_best_path_reroutes(toy):
    # Best path is A-C-B-D-E (10). Close C->B: best becomes A-B-D-E (11).
    d = DStarLite(to_adjacency(toy), "A", "E")
    assert d.get_path() == ["A", "C", "B", "D", "E"]
    d.close_edge("C", "B")
    toy["C"]["B"]["free_flow_time"] = math.inf
    assert d.get_path() == ["A", "B", "D", "E"]
    assert d.path_cost() == 11
    assert close(d.path_cost(), astar_cost(toy, "A", "E"))


def test_reopen_restores_old_route(toy):
    d = DStarLite(to_adjacency(toy), "A", "E")
    d.get_path()
    d.close_edge("C", "B")
    assert d.path_cost() == 11
    d.reopen_edge("C", "B")                       # back to its old cost 1
    assert d.get_path() == ["A", "C", "B", "D", "E"]
    assert d.path_cost() == 10
    d.close_edge("C", "B")
    d.reopen_edge("C", "B", 3)                    # reopened slower: 2+3+5+2
    assert d.path_cost() == 11


def test_update_edge_cost_accepts_inf_as_closure(toy):
    d = DStarLite(to_adjacency(toy), "A", "E")
    d.get_path()
    d.update_edge_cost("C", "B", math.inf)
    assert d.get_path() == ["A", "B", "D", "E"]


def test_closure_that_makes_goal_unreachable(toy):
    d = DStarLite(to_adjacency(toy), "A", "E")
    d.get_path()
    d.close_edge("D", "E")
    d.close_edge("C", "E")
    assert d.get_path() == []
    assert d.path_cost() == math.inf
    d.reopen_edge("D", "E")
    assert d.get_path() == ["A", "C", "B", "D", "E"]


def test_reopen_errors(toy):
    d = DStarLite(to_adjacency(toy), "A", "E")
    with pytest.raises(KeyError):
        d.reopen_edge("A", "B")                   # not closed, no cost given
    d.close_edge("A", "B")
    with pytest.raises(ValueError):
        d.reopen_edge("A", "B", math.inf)
    with pytest.raises(KeyError):
        d.close_edge("B", "A")                    # no such road


@pytest.mark.parametrize("seed", range(100))
def test_random_changes_with_closures_match_fresh_astar(seed):
    """Cost changes, closures and reopenings, checked against A* each time."""
    rnd = random.Random(1000 + seed)
    G = grid(rnd.randint(2, 5), rnd.randint(2, 5),
             weights=lambda r: r.randint(1, 9))
    s, t = rnd.sample(list(G.nodes), 2)
    d = DStarLite(to_adjacency(G), s, t)
    for _ in range(15):
        u, v = rnd.choice(list(G.edges))
        roll = rnd.random()
        if roll < 0.3:
            d.close_edge(u, v)
            G[u][v]["free_flow_time"] = math.inf
        elif roll < 0.5 and (u, v) in d.closed:
            w = rnd.randint(1, 9)
            d.reopen_edge(u, v, w)
            G[u][v]["free_flow_time"] = w
        else:
            w = rnd.randint(1, 20)
            d.update_edge_cost(u, v, w)
            G[u][v]["free_flow_time"] = w
            d.closed.pop((u, v), None)
        assert close(d.path_cost(), astar_cost(G, s, t))


# ---------------------------------------------------------------------------
# f) Edge cases from the review: dead-end goal, zero-cost roads
# ---------------------------------------------------------------------------
def test_dead_end_goal_without_its_own_key():
    # Node 3 has no roads out and is not a key: still a valid goal.
    d = DStarLite({1: {2: 1.0}, 2: {3: 1.0}}, 1, 3)
    assert d.get_path() == [1, 2, 3]
    assert d.path_cost() == 2


def test_zero_cost_roads_find_the_path():
    d = DStarLite({1: {2: 0}, 2: {1: 0, 3: 1}, 3: {}}, 1, 3)
    assert d.get_path() == [1, 2, 3]
    assert d.path_cost() == 1


def test_zero_cost_cycle_with_equal_values():
    # All of 1, 2, 3 have cost-to-goal 1; the path must not loop.
    d = DStarLite({1: {2: 0}, 2: {1: 0, 3: 0}, 3: {2: 0, 4: 1}, 4: {}}, 1, 4)
    assert d.get_path() == [1, 2, 3, 4]
    assert d.path_cost() == 1


# ---------------------------------------------------------------------------
# g) from_networkx
# ---------------------------------------------------------------------------
def test_from_networkx_keeps_cheapest_parallel_road_and_dead_ends():
    G = nx.MultiDiGraph()
    G.add_edge("A", "B", free_flow_time=5)
    G.add_edge("A", "B", free_flow_time=2)        # parallel, cheaper
    G.add_edge("B", "C", free_flow_time=1)        # C has no roads out
    d = DStarLite.from_networkx(G, "A", "C")
    assert d.graph == {"A": {"B": 2.0}, "B": {"C": 1.0}, "C": {}}
    assert d.get_path() == ["A", "B", "C"]
    assert d.path_cost() == 3


def test_from_networkx_with_cost_function(toy):
    double = DStarLite.from_networkx(
        toy, "A", "E", cost=lambda u, v, data: 2 * data["free_flow_time"])
    assert double.path_cost() == 20


def test_from_networkx_matches_astar_on_real_map():
    from src.world.graph_loader import load_road_graph
    G = load_road_graph("secunderabad_small")
    nodes = sorted(G.nodes)
    rnd = random.Random(7)
    for _ in range(3):
        s, t = rnd.sample(nodes, 2)
        d = DStarLite.from_networkx(G, s, t)
        ref = astar(G, s, t).cost
        assert close(d.path_cost(), ref)
        path = d.get_path()
        if len(path) > 2:                         # close a road on the route
            u, v = path[0], path[1]
            d.close_edge(u, v)

            def blocked(a, b, data, u=u, v=v):
                return math.inf if (a, b) == (u, v) else data["free_flow_time"]
            assert close(d.path_cost(), astar(G, s, t, blocked).cost)


# ---------------------------------------------------------------------------
# h) Expansion counter
# ---------------------------------------------------------------------------
def test_expanded_counts_work_per_repair(toy):
    d = DStarLite(to_adjacency(toy), "A", "E")
    d.get_path()
    assert d.expanded == 5                        # E, D, B, C, A
    d.get_path()
    assert d.expanded == 0                        # nothing changed
    d.update_edge_cost("C", "B", 100)
    d.get_path()
    assert d.expanded == 4                        # C twice, A twice
    assert d.total_expanded == 9


# ---------------------------------------------------------------------------
# i) Week 2: heuristic, km as the vehicle moves, 500-change property tests
# ---------------------------------------------------------------------------
def manhattan(a, b):
    """Admissible on grid() graphs: every road costs at least 1."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def random_event(rnd, G, d):
    """Apply one random change to both G and d: cost change, close, reopen."""
    u, v = rnd.choice(list(G.edges))
    roll = rnd.random()
    if roll < 0.25:
        d.close_edge(u, v)
        G[u][v]["free_flow_time"] = math.inf
    elif roll < 0.45 and (u, v) in d.closed:
        w = rnd.randint(1, 9)
        d.reopen_edge(u, v, w)
        G[u][v]["free_flow_time"] = w
    else:
        w = rnd.randint(1, 20)
        d.update_edge_cost(u, v, w)
        G[u][v]["free_flow_time"] = w
        d.closed.pop((u, v), None)


def test_heuristic_grid_all_pairs_matches_astar():
    G = grid(4, 4, weights=lambda rnd: rnd.randint(1, 9))
    for s in G.nodes:
        for t in G.nodes:
            d = DStarLite(to_adjacency(G), s, t, heuristic=manhattan)
            assert close(d.path_cost(), astar_cost(G, s, t)), (s, t)


def test_heuristic_expands_fewer_nodes():
    G = grid(10, 10)
    plain = DStarLite(to_adjacency(G), (0, 0), (0, 9))
    guided = DStarLite(to_adjacency(G), (0, 0), (0, 9), heuristic=manhattan)
    assert plain.path_cost() == guided.path_cost() == 9
    assert guided.expanded < plain.expanded


def test_km_grows_by_heuristic_of_each_move():
    G = grid(5, 5, weights=lambda rnd: rnd.randint(1, 9))
    goal = (4, 4)
    d = DStarLite(to_adjacency(G), (0, 0), goal, heuristic=manhattan)
    rnd = random.Random(3)
    expected_km = 0
    while d.start != goal:
        random_event(rnd, G, d)
        assert close(d.path_cost(), astar_cost(G, d.start, goal))
        path = d.get_path()
        if not path:
            break
        expected_km += manhattan(d.start, path[1])
        d.move_start(path[1])
        assert close(d.km, expected_km)        # (heuristic has 1e-9 slack)
    assert d.km > 0


def test_from_networkx_passes_heuristic(toy):
    d = DStarLite.from_networkx(toy, "A", "E", heuristic=lambda a, b: 0)
    assert d.path_cost() == 10


def drive_with_changes(rnd, G, d, goal, steps):
    """Random changes, the vehicle sometimes moving one road along its route.

    After every change D* Lite's cost must equal a fresh A* run.
    """
    for _ in range(steps):
        random_event(rnd, G, d)
        assert close(d.path_cost(), astar_cost(G, d.start, goal))
        path = d.get_path()
        if len(path) > 1 and rnd.random() < 0.3:
            d.move_start(path[1])


@pytest.mark.parametrize("seed", range(500))
def test_500_random_change_sequences(seed):
    """Plan's Definition of Done: D* Lite cost equals A* over 500 sequences."""
    rnd = random.Random(5000 + seed)
    G = grid(rnd.randint(2, 6), rnd.randint(2, 6),
             weights=lambda r: r.randint(1, 9))
    s, t = rnd.sample(list(G.nodes), 2)
    h = manhattan if seed % 2 else None
    d = DStarLite(to_adjacency(G), s, t, heuristic=h)
    drive_with_changes(rnd, G, d, t, steps=10)


@pytest.mark.parametrize("use_heuristic", [False, True])
def test_500_changes_in_one_run(use_heuristic):
    """Week 2 property test: 500 random edge changes on one planner."""
    rnd = random.Random(42)
    G = grid(8, 8, weights=lambda r: r.randint(1, 9))
    h = manhattan if use_heuristic else None
    d = DStarLite(to_adjacency(G), (0, 0), (7, 7), heuristic=h)
    drive_with_changes(rnd, G, d, (7, 7), steps=500)


def test_500_changes_on_real_map_with_haversine_heuristic():
    """Real Secunderabad (small) graph, R2's heuristic, 500 changes.

    Costs only go up from free-flow time (traffic) or to inf (closure), and
    reopened roads go back to free-flow, so the heuristic stays admissible.
    """
    from src.search.heuristics import make_heuristic
    from src.world.graph_loader import load_road_graph
    G = load_road_graph("secunderabad_small")
    h = make_heuristic(G)
    rnd = random.Random(11)
    nodes = sorted(G.nodes)
    while True:
        s, t = rnd.sample(nodes, 2)
        if astar(G, s, t).cost < math.inf:
            break
    d = DStarLite.from_networkx(G, s, t, heuristic=h)
    base = {(u, v): data["free_flow_time"]
            for u, v, data in G.edges(data=True)}
    now = dict(base)
    on_route = []

    def cost_now(u, v, data):
        return now[(u, v)]

    for step in range(500):
        if on_route and rnd.random() < 0.5:
            u, v = rnd.choice(on_route)          # changes near the vehicle
        else:
            u, v = rnd.choice(list(base))
        roll = rnd.random()
        if roll < 0.2:
            d.close_edge(u, v)
            now[(u, v)] = math.inf
        elif roll < 0.35 and (u, v) in d.closed:
            d.reopen_edge(u, v, base[(u, v)])
            now[(u, v)] = base[(u, v)]
        else:
            c = base[(u, v)] * rnd.uniform(1, 5)
            d.update_edge_cost(u, v, c)
            now[(u, v)] = c
            d.closed.pop((u, v), None)
        assert close(d.path_cost(), astar(G, d.start, t, cost_now).cost)
        path = d.get_path()
        on_route = list(zip(path, path[1:]))
        if len(path) > 1 and rnd.random() < 0.2:
            d.move_start(path[1])
    assert d.km > 0


def test_full_map_heuristic_replans_match_astar():
    """Regression: R2's heuristic is exact on straight roads, so rounding
    could stop the repair loop one node early (trips 24 and 26 of this seed
    returned no path). Fixed by H_SLACK in DStarLite.heuristic.
    """
    from src.search.heuristics import make_heuristic
    from src.world.graph_loader import load_road_graph
    G = load_road_graph("secunderabad")
    h = make_heuristic(G)
    nodes = sorted(G.nodes)
    rnd = random.Random(42)
    trips = 0
    while trips < 30:
        s, t = rnd.sample(nodes, 2)
        first = astar(G, s, t)
        if first.cost == math.inf or len(first.path) < 6:
            continue
        trips += 1
        d = DStarLite.from_networkx(G, s, t, heuristic=h)
        path = d.get_path()
        assert close(d.path_cost(path), first.cost)
        i = len(path) // 2
        u, v = path[i], path[i + 1]
        slow = d.graph[u][v] * 5
        d.update_edge_cost(u, v, slow)

        def cost_fn(a, b, data, u=u, v=v, slow=slow):
            return slow if (a, b) == (u, v) else data["free_flow_time"]
        assert close(d.path_cost(), astar(G, s, t, cost_fn).cost), trips


# ---------------------------------------------------------------------------
# j) Week 3: debug check when a cost drops below the heuristic (R2 review)
# ---------------------------------------------------------------------------
def test_warns_when_cost_below_heuristic():
    from src.search.dstar_lite import HeuristicWarning
    G = grid(3, 3)                                   # unit costs, Manhattan ok
    d = DStarLite(to_adjacency(G), (0, 0), (2, 2), heuristic=manhattan)
    with pytest.warns(HeuristicWarning):
        d.update_edge_cost((0, 0), (0, 1), 0.5)      # h says at least 1


def test_no_warning_for_valid_changes_or_without_heuristic():
    import warnings
    G = grid(3, 3)
    guided = DStarLite(to_adjacency(G), (0, 0), (2, 2), heuristic=manhattan)
    plain = DStarLite(to_adjacency(G), (0, 0), (2, 2))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        guided.update_edge_cost((0, 0), (0, 1), 3)   # slower: fine
        guided.close_edge((0, 1), (0, 2))            # inf: fine
        guided.update_edge_cost((1, 1), (1, 2), 1)   # exactly the bound: fine
        plain.update_edge_cost((0, 0), (0, 1), 0)    # no heuristic: no check
