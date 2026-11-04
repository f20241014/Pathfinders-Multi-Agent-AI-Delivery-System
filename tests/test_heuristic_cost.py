"""Tiny run of src/search/heuristic_cost.py: it runs and returns positive numbers.

Run from the repo root:  python -m pytest tests/test_heuristic_cost.py
"""
from src.search.benchmark import MEASURED_HEADER, random_od_pairs
from src.search.heuristic_cost import measure, write_section
from src.world.graph_loader import load_road_graph


def test_runs_and_returns_positive_numbers(tmp_path):
    G = load_road_graph("secunderabad")
    res = measure(G, random_od_pairs(G, 8, seed=42), n_calls=2000, seed=42)
    assert res["calls_mean"] > 0 and res["calls_median"] > 0
    assert res["us_heuristic"] > 0 and res["us_edge_cost"] > 0 and res["us_empty_loop"] > 0
    assert all(ms > 0 for ms in res["ms_mean"].values())

    path = tmp_path / "bench.md"
    path.write_text("# Benchmark\n\ntable\n", encoding="utf-8")
    write_section(res, path)
    write_section(res, path)                               # running twice replaces, not adds
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Benchmark") and text.count(MEASURED_HEADER) == 1
