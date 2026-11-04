"""Smoke test for src/search/benchmark_replan.py (R7, Week 3).

run() itself asserts that D* Lite and A* agree on every replan, so a small
run on the small map checks correctness, the CSV and the figure.
"""
from src.search import benchmark_replan as b
from src.search.benchmark_replan import choose_roads, run, summarise


def test_small_run_agrees_with_astar_and_plots(tmp_path):
    rows = run(graph_name="secunderabad_small", trips=2, ks=(1, 5, 20), seed=1)
    assert len(rows) == 2 * 3 * 3
    assert all(r["dstar_cpu_ms"] >= 0 and r["astar_expanded"] > 0 for r in rows)
    summary = summarise(rows)
    assert {s["placement"] for s in summary} == set(b.PLACEMENTS)
    b.write_csv(rows, tmp_path / "bench.csv")
    b.plot(summary, tmp_path / "f3.png")
    assert (tmp_path / "f3.png").stat().st_size > 10_000


def test_choose_roads_placements():
    import random
    path = [1, 2, 3, 4]
    roads = [(1, 2), (2, 3), (3, 4), (5, 6), (6, 7)]
    rnd = random.Random(0)
    assert choose_roads(path, roads, 2, "near_vehicle", rnd) == [(1, 2), (2, 3)]
    assert choose_roads(path, roads, 2, "near_goal", rnd) == [(3, 4), (2, 3)]
    picked = choose_roads(path, roads, 5, "near_goal", rnd)
    assert len(set(picked)) == 5
