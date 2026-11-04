"""Tests for src/search/fifo_check.py on hand-made travel-time functions.

Run from the repo root:  python -m pytest tests/test_fifo_check.py
"""
import math

import networkx as nx
import pytest

from src.search.fifo_check import (check_edge, check_fifo, conclusion, sample_edges,
                                   write_doc)
from src.sim.world import FakeWorld

TIMES = range(0, 100)          # one-second grid 0..99


def test_constant_time_is_fifo():
    assert check_edge(lambda u, v, t: 10.0, 1, 2, TIMES) == ("ok", 0.0, None, 0)


def test_slope_minus_one_is_still_fifo():
    # T(t) = 200 - t: every car leaves at exactly t + T = 200 (a tie, not an overtake).
    assert check_edge(lambda u, v, t: 200.0 - t, 1, 2, TIMES) == ("ok", 0.0, None, 0)


def test_sudden_drop_is_a_violation():
    # T = 100 s before t = 50, then 10 s. Car in at 49 leaves at 149; car in at 50
    # leaves at 60, so it is overtaken by 89 s (the worst, at t = 50).
    # Exit(t2) = t2 + 10 < 149 for every t2 = 50..99, so 50 grid times violate.
    def drop(u, v, t):
        return 100.0 if t < 50 else 10.0
    assert check_edge(drop, 1, 2, TIMES) == ("ok", 89.0, 50, 50)


def test_closed_edge_is_skipped_not_checked():
    def closed_later(u, v, t):
        return math.inf if t >= 30 else 10.0
    assert check_edge(closed_later, 1, 2, TIMES)[0] == "closed"

    def fn(u, v, t):
        return closed_later(u, v, t) if (u, v) == (1, 2) else 5.0
    s = check_fifo(fn, [(1, 2), (2, 3)], TIMES)
    assert s["edges_closed_skipped"] == 1 and s["edges_checked"] == 1


def test_summary_reports_worst_edge():
    def fn(u, v, t):
        if (u, v) == ("b", "c"):
            return 100.0 if t < 50 else 10.0
        return 10.0
    s = check_fifo(fn, [("a", "b"), ("b", "c")], TIMES)
    assert s["edges_checked"] == 2 and s["edges_violating"] == 1
    assert s["worst_s"] == pytest.approx(89.0) and s["worst_edge"] == ("b", "c")
    assert s["worst_t"] == 50 and s["grid_times"] == 2 * len(TIMES)


def test_free_flow_world_has_no_violations():
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, free_flow_time=10.0)
    G.add_edge(2, 3, free_flow_time=20.0)
    world = FakeWorld(G)
    s = check_fifo(world.edge_time, sample_edges(G, 10, seed=0), range(21600, 36001, 60))
    assert s["edges_checked"] == 2 and s["edges_violating"] == 0


def test_sample_edges_is_fixed_by_seed():
    G = nx.gnm_random_graph(50, 200, seed=1, directed=True)
    assert sample_edges(G, 20, seed=5) == sample_edges(G, 20, seed=5)
    assert len(set(sample_edges(G, 20, seed=5))) == 20


def test_doc_warns_when_free_flow_only(tmp_path):
    summary = check_fifo(lambda u, v, t: 1.0, [(1, 2)], TIMES)
    path = tmp_path / "fifo.md"
    write_doc({1: summary}, has_traffic=False, n_edges=1, seed=0, prediction="", path=path)
    first = path.read_text(encoding="utf-8").splitlines()[0]
    assert "free-flow only (no traffic data), result is trivial and NOT valid evidence" in first


def test_conclusion_uses_the_numbers():
    def summary(violating, times, worst):
        return {"edges_checked": 500, "edges_violating": violating, "violating_times": times,
                "grid_times": 1_000_000, "worst_s": worst}
    text = " ".join(conclusion({5: summary(74, 500, 57.7), 1: summary(303, 900, 61.71)}, 500))
    assert ("14.8% of edges violate FIFO on a 5 s grid and 60.6% on a 1 s grid, "
            "at fewer than 0.1% of the grid times; the worst case is 61.7 s.") in text
    no_violation = " ".join(conclusion({1: summary(0, 0, 0.0)}, 500))
    assert "No FIFO violation was found" in no_violation
