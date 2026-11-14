"""Order generator: R1 Order, units in docs/kr_ontology_rules.md, reproducibility, statistics."""

import numpy as np
import pandas as pd
import pytest

from src.data.orders_from_amazon import Empirical, compare_to_empirical, generate, order_summary
from src.kr.ontology import NO_TW_END, NO_TW_START, SIM_END_S, SIM_START_S, tw_of
from src.sim.models import Order as SimOrder


@pytest.fixture
def emp(tmp_path):
    rng = np.random.default_rng(1)
    n = 2000
    stops = pd.DataFrame(
        {
            "route_id": "R",
            "stop_id": [f"S{i}" for i in range(n)],
            "n_packages": rng.integers(1, 4, n),
            "service_sum_s": rng.gamma(2, 40, n),
        }
    )
    has = rng.random(n) < 0.1
    pk = pd.DataFrame(
        {
            "route_id": "R",
            "stop_id": stops["stop_id"],
            "volume_cm3": rng.lognormal(8, 1, n),
            "has_tw": has,
            "tw_width_h": np.where(has, rng.uniform(1, 4, n), np.nan),
            "tw_start_after_dep_h": np.where(has, rng.uniform(0, 8, n), np.nan),
        }
    )
    stops.to_csv(tmp_path / "packages_per_stop.csv", index=False)
    pk.to_csv(tmp_path / "packages.csv", index=False)
    return Empirical(tmp_path)


@pytest.fixture
def nodes():
    rng = np.random.default_rng(2)
    return pd.DataFrame({"node": np.arange(500), "x": rng.random(500), "y": rng.random(500)})


@pytest.mark.parametrize("layout", ["uniform", "clustered", "hotspot"])
def test_invariants(emp, nodes, layout):
    os_ = generate(emp, nodes, 300, seed=0, layout=layout, depot_nodes=(0, 1))
    assert len(os_) == 300 and len({o.id for o in os_}) == 300
    for o in os_:
        assert isinstance(o, SimOrder)  # R1's Order, not a copy
        assert o.node not in (0, 1)
        assert o.demand >= 1 and o.priority in (1, 2, 3)
        assert SIM_START_S <= o.release_time <= SIM_END_S  # seconds since midnight, 06:00-10:00
        tw = tw_of(o)
        if tw is None:
            assert (o.tw_start, o.tw_end) == (NO_TW_START, NO_TW_END)  # R1's defaults
        else:
            assert o.release_time <= tw[0] < tw[1] <= SIM_END_S


def test_same_seed_same_orders(emp, nodes):
    assert generate(emp, nodes, 50, seed=7) == generate(emp, nodes, 50, seed=7)
    assert generate(emp, nodes, 50, seed=7) != generate(emp, nodes, 50, seed=8)


def test_hotspot_concentrates_demand(emp, nodes):
    def top20(os_):
        return pd.Series([o.node for o in os_]).value_counts().iloc[:20].sum()

    assert top20(generate(emp, nodes, 300, seed=0, layout="hotspot")) > top20(
        generate(emp, nodes, 300, seed=0, layout="uniform")
    )


def test_summary_counts_windows_correctly(emp, nodes):
    os_ = generate(emp, nodes, 300, seed=0)
    s = order_summary(os_)
    assert s["with_time_window"] == sum(
        (o.tw_start, o.tw_end) != (NO_TW_START, NO_TW_END) for o in os_
    )
    assert 0 < s["without_time_window"] < 300
    assert s["with_time_window"] + s["without_time_window"] == 300
    assert 0 < s["dynamic"] < 300


def test_statistics_match(emp, nodes):
    r = compare_to_empirical(generate(emp, nodes, 300, seed=0), emp)
    assert r["service_time"] > 0.01
    assert abs(r["share_with_tw_generated"] - r["share_with_tw_empirical"]) < 0.06


def test_no_field_is_none(emp, nodes):
    for o in generate(emp, nodes, 300, seed=0):
        assert all(v is not None for v in vars(o).values()), o


def test_tw_of_reads_r1_defaults_as_no_window():
    assert tw_of(SimOrder("a", 1, 1)) is None  # R1's defaults 0.0 / 86400.0
    assert tw_of(SimOrder("b", 1, 1, tw_start=0.0, tw_end=86400.0)) is None
    assert tw_of(SimOrder("c", 1, 1, tw_start=21600.0, tw_end=86400.0)) == (21600.0, 86400.0)
    assert tw_of(SimOrder("d", 1, 1, tw_start=0.0, tw_end=30000.0)) == (0.0, 30000.0)
    assert tw_of(SimOrder("e", 1, 1, tw_start=None, tw_end=None)) is None  # older objects

