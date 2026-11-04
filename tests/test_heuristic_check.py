"""Tests for src/search/heuristic_check.py (fast version: 20 targets, 20 pairs).

networkx is used here only as a reference answer.
Run from the repo root:  python -m pytest tests/test_heuristic_check.py
"""
import math

import networkx as nx
import pytest

from src.search.heuristic_check import (edge_costs, reverse_dijkstra, run, static_check,
                                        write_doc)
from src.sim.world import World


@pytest.fixture
def toy():
    #   A -4-> B -5-> D -2-> E,  A -2-> C -1-> B,  C -8-> D,  C -10-> E
    G = nx.MultiDiGraph()
    for u, v, t in [("A", "B", 4), ("A", "C", 2), ("C", "B", 1), ("B", "D", 5),
                    ("C", "D", 8), ("C", "E", 10), ("D", "E", 2)]:
        G.add_edge(u, v, free_flow_time=t)
    G.add_edge("D", "E", free_flow_time=9)            # slower parallel road: ignored
    return G


def test_reverse_dijkstra_by_hand_and_vs_networkx(toy):
    true = reverse_dijkstra(edge_costs(toy), "E")
    assert true == {"E": 0, "D": 2, "B": 7, "C": 8, "A": 10}      # by hand
    D = nx.DiGraph()
    for (u, v), c in edge_costs(toy).items():
        D.add_edge(u, v, w=c)
    assert true == nx.shortest_path_length(D, target="E", weight="w")


def test_good_heuristic_passes(toy):
    exact = reverse_dijkstra(edge_costs(toy), "E")
    admissible, consistent = static_check(toy, ["E"], lambda n, goal: exact[n])
    assert admissible["violations"] == 0 and consistent["violations"] == 0
    assert admissible["min_slack"] == 0.0            # the exact cost-to-go has zero slack


def test_overestimating_heuristic_is_caught(toy):
    exact = reverse_dijkstra(edge_costs(toy), "E")
    admissible, _ = static_check(toy, ["E"], lambda n, goal: 2 * exact[n])
    assert admissible["violations"] == 4                 # every node except the target
    assert admissible["worst"] == 10.0                   # A: h = 20, true = 10


@pytest.fixture(scope="module")
def results():
    return run(World.from_defaults(), n_targets=20, n_pairs=20, seed=0,
               n_ratio_edges=50, ratio_step=600)


def test_real_graph_static_checks(results):
    assert results["admissible"]["checked"] == 20 * (results["nodes"] - 1)
    assert results["admissible"]["violations"] == 0
    assert results["consistent"]["violations"] == 0


def test_real_graph_time_dependent_checks(results):
    assert results["has_traffic"], "traffic model must be active for this test"
    assert results["min_ratio"] >= 1.0
    assert results["td"]["checked"] > 0 and results["td"]["violations"] == 0


def test_doc_claims_nothing_without_traffic(results, tmp_path):
    path = tmp_path / "h.md"
    write_doc(dict(results, has_traffic=False), "", path=path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("**Traffic model NOT active")
    assert "No result is claimed" in text and "(b1) Smallest" not in text
    assert math.isfinite(results["admissible"]["min_slack"])
