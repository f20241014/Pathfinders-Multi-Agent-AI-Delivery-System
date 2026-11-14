"""R3 data pipeline: clean_json -> profile_amazon -> order generator.

The sample in tests/fixtures/amazon_sample always runs. Tests on the real Amazon download skip
when data/raw / data/cleaned are missing (CI never has them).
"""

import json
import random
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest

from src.data.orders_from_amazon import Empirical, OrderSampler, order_summary
from src.data.profile_amazon import profile, write_outputs
from src.kr.ontology import NO_TW_END, NO_TW_START, SIM_END_S, SIM_START_S, tw_of
from src.sim.run import build_order

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "amazon_sample"
REAL_ROUTES = ROOT / "data" / "raw" / "route_data.json"
REAL_PACKAGES = ROOT / "data" / "cleaned" / "package_data.json"
needs_real_data = pytest.mark.skipif(
    not (REAL_ROUTES.exists() and REAL_PACKAGES.exists()),
    reason="Amazon data not downloaded/cleaned (see docs/data_profile.md)",
)


def test_clean_json_replaces_nan(tmp_path):
    # .txt on purpose: it holds bare NaN like the real download (not valid JSON)
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    shutil.copy(SAMPLE / "package_data_raw.txt", raw / "package_data.json")
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "clean_json.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "NaN values replaced: 14" in out.stdout
    cleaned = json.loads((tmp_path / "data" / "cleaned" / "package_data.json").read_text())
    assert cleaned == json.loads((SAMPLE / "package_data.json").read_text())


def test_profile_on_sample(tmp_path):
    R, S, P = profile(SAMPLE / "route_data.json", SAMPLE / "package_data.json")
    assert sorted(R["n_stops"]) == [1, 2, 3]  # Station stops are not counted
    assert len(S) == 6 and len(P) == 9
    assert P["has_tw"].sum() == 2
    assert P.loc[P["has_tw"], "tw_width_h"].tolist() == [3.0, 4.0]
    assert P.loc[P["has_tw"], "tw_start_after_dep_h"].tolist() == [2.0, 1.5]
    summary = write_outputs(R, S, P, tmp_path, plots=False)
    assert summary["share_stops_with_any_tw"] == round(2 / 6, 4)
    assert (tmp_path / "packages.csv").exists()


def test_profile_max_routes(tmp_path):
    R, _, _ = profile(SAMPLE / "route_data.json", SAMPLE / "package_data.json", max_routes=2)
    assert len(R) == 2


@pytest.fixture(scope="module")
def sample_sampler(tmp_path_factory):
    d = tmp_path_factory.mktemp("profile")
    write_outputs(
        *profile(SAMPLE / "route_data.json", SAMPLE / "package_data.json"), d, plots=False
    )
    nodes = pd.DataFrame(
        {"node": range(40), "x": [i % 7 for i in range(40)], "y": [i // 7 for i in range(40)]}
    )
    return OrderSampler(Empirical(d), nodes, "clustered", zone_seed=1, depot_nodes=(0,), n_zones=4)


def test_generator_runs_on_sample(sample_sampler):
    orders = sample_sampler.generate(60, seed=0)
    s = order_summary(orders)
    assert s["orders"] == 60 and s["with_time_window"] + s["without_time_window"] == 60
    assert s["with_time_window"] == sum(tw_of(o) is not None for o in orders)
    assert s["dynamic"] > 0  # D3: some release_time > start
    for o in orders:
        assert o.node != 0 and o.demand >= 1
        assert SIM_START_S <= o.release_time <= SIM_END_S
        tw = tw_of(o)
        assert tw is None or (o.release_time <= tw[0] < tw[1] <= SIM_END_S)
        assert tw is not None or (o.tw_start, o.tw_end) == (NO_TW_START, NO_TW_END)


def test_generate_order_single(sample_sampler):
    t = SIM_START_S + 3600
    a = sample_sampler.generate_order(random.Random(5), t)
    b = sample_sampler.generate_order(random.Random(5), t, order_id=a.id)
    assert a == b and a.release_time == t and a.id.startswith("dyn_")
    tw = tw_of(a)
    assert tw is None or tw[0] >= t


def test_generator_uses_local_rng(sample_sampler):
    random.seed(1)
    before = random.random()
    random.seed(1)
    sample_sampler.generate(20, seed=3)
    assert random.random() == before  # global random state untouched
    assert sample_sampler.generate(20, seed=3) == sample_sampler.generate(20, seed=3)


def test_orders_load_in_r1_after_json_round_trip(sample_sampler):
    """30 orders -> asdict -> JSON -> R1's build_order: nothing None, R1's window checks run."""
    orders = sample_sampler.generate(30, seed=0)
    assert any(tw_of(o) is None for o in orders) and any(tw_of(o) for o in orders)
    loaded = [build_order(d) for d in json.loads(json.dumps([asdict(o) for o in orders]))]
    assert loaded == orders
    for o in loaded:
        assert all(v is not None for v in asdict(o).values()), o.id
        # the exact comparisons src/sim/environment.py makes (they raised TypeError on None)
        assert isinstance(max(o.tw_start, o.release_time) > o.tw_end, bool)
        assert isinstance(SIM_START_S > o.tw_end, bool)


def test_export_nodes_matches_the_simulators_graph(tmp_path):
    from src.world.graph_loader import load_road_graph

    out = tmp_path / "nodes.csv"
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_nodes.py"), "--graph",
         "secunderabad_small", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    nodes = pd.read_csv(out)
    G = load_road_graph("secunderabad_small")
    assert list(nodes.columns) == ["node", "x", "y"]
    assert set(nodes["node"]) == set(G.nodes) and f"wrote {len(nodes)} nodes" in res.stdout
    assert nodes[["x", "y"]].notna().all().all()


@needs_real_data
def test_profile_on_real_data(tmp_path):
    R, S, P = profile(REAL_ROUTES, REAL_PACKAGES, max_routes=50)
    assert len(R) == 50 and (R["n_stops"] > 0).all()


@needs_real_data
def test_real_profile_has_time_windows(tmp_path):
    _, _, P = profile(REAL_ROUTES, REAL_PACKAGES, max_routes=50)
    assert 0 < P["has_tw"].mean() < 1


@needs_real_data
def test_generator_on_real_profile(tmp_path):
    write_outputs(*profile(REAL_ROUTES, REAL_PACKAGES, max_routes=50), tmp_path, plots=False)
    nodes = pd.DataFrame({"node": range(100), "x": range(100), "y": range(100)})
    orders = OrderSampler(Empirical(tmp_path), nodes).generate(100, seed=0)
    assert len(orders) == 100