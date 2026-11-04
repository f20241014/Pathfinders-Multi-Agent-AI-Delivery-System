"""Fast version of src/search/benchmark.py: 20 pairs, outputs written to a temp folder.

Run from the repo root:  python -m pytest tests/test_benchmark.py
"""
import csv
import math

import pytest

from src.search.benchmark import (plot, random_od_pairs, run_benchmark, summarise,
                                  write_csv, write_markdown)
from src.world.graph_loader import load_road_graph


@pytest.fixture(scope="module")
def rows():
    G = load_road_graph("secunderabad")
    return run_benchmark(G, random_od_pairs(G, 20, seed=7))


def test_costs_equal_on_every_pair(rows):
    assert len(rows) == 20
    for r in rows:
        assert math.isclose(r["dijkstra_cost_s"], r["astar_cost_s"], rel_tol=1e-9, abs_tol=1e-6)
        assert r["dijkstra_expanded"] >= 1 and r["astar_expanded"] >= 1


def test_pairs_fixed_by_seed():
    G = load_road_graph("secunderabad")
    assert random_od_pairs(G, 5, seed=7) == random_od_pairs(G, 5, seed=7)


def test_outputs_are_written(rows, tmp_path):
    summary = summarise(rows)
    csv_path, md_path = tmp_path / "b.csv", tmp_path / "b.md"
    fig_path = tmp_path / "F2.png"
    write_csv(rows, csv_path)
    write_markdown(summary, "my guess", seed=7, path=md_path)
    plot(rows, fig_path)

    with open(csv_path, encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 20
    text = md_path.read_text(encoding="utf-8")
    assert "> my guess" in text and "Ratio Dijkstra / A*" in text
    assert fig_path.stat().st_size > 10_000
