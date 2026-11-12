"""Order generator: R1 Order, units in docs/kr_ontology_rules.md, reproducibility, statistics."""

import numpy as np
import pandas as pd
import pytest

from src.data.orders_from_amazon import Empirical, compare_to_empirical, generate, order_summary
from src.kr.ontology import SIM_END_S, SIM_START_S, tw_of
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
            assert o.tw_start is None and o.tw_end is None  # one marker for "no window"
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
    assert s["with_time_window"] == sum(o.tw_start is not None for o in os_)
    assert s["with_time_window"] + s["without_time_window"] == 300
    assert 0 < s["dynamic"] < 300


def test_statistics_match(emp, nodes):
    r = compare_to_empirical(generate(emp, nodes, 300, seed=0), emp)
    assert r["service_time"] > 0.01
    assert abs(r["share_with_tw_generated"] - r["share_with_tw_empirical"]) < 0.06
