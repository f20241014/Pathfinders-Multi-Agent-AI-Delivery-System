"""Order generator v1: interface fields, invariants, reproducibility, statistics match."""
import numpy as np
import pandas as pd
import pytest

from src.data.orders_from_amazon import Empirical, compare_to_empirical, generate


@pytest.fixture
def emp(tmp_path):
    rng = np.random.default_rng(1)
    n = 2000
    stops = pd.DataFrame({"route_id": "R", "stop_id": [f"S{i}" for i in range(n)],
                          "n_packages": rng.integers(1, 4, n), "service_sum_s": rng.gamma(2, 40, n)})
    has = rng.random(n) < 0.1
    pk = pd.DataFrame({"route_id": "R", "stop_id": stops["stop_id"], "volume_cm3": rng.lognormal(8, 1, n),
                       "has_tw": has, "tw_width_h": np.where(has, rng.uniform(1, 4, n), np.nan),
                       "tw_start_after_dep_h": np.where(has, rng.uniform(0, 8, n), np.nan)})
    stops.to_csv(tmp_path / "packages_per_stop.csv", index=False)
    pk.to_csv(tmp_path / "packages.csv", index=False)
    return Empirical(tmp_path)


@pytest.fixture
def nodes():
    rng = np.random.default_rng(2)
    return pd.DataFrame({"node": np.arange(500), "x": rng.random(500), "y": rng.random(500)})


@pytest.mark.parametrize("layout", ["uniform", "clustered", "hotspot"])
def test_invariants(emp, nodes, layout):
    H = 4 * 3600
    os_ = generate(emp, nodes, 300, seed=0, layout=layout, depot_nodes=(0, 1))
    assert len(os_) == 300 and len({o.id for o in os_}) == 300
    for o in os_:
        assert o.node not in (0, 1)
        assert o.demand >= 1 and o.priority in (1, 2, 3)
        assert 0 <= o.release_time <= H
        if o.has_tw:
            assert o.release_time <= o.tw_start < o.tw_end <= H


def test_same_seed_same_orders(emp, nodes):
    assert generate(emp, nodes, 50, seed=7) == generate(emp, nodes, 50, seed=7)
    assert generate(emp, nodes, 50, seed=7) != generate(emp, nodes, 50, seed=8)


def test_hotspot_concentrates_demand(emp, nodes):
    u = generate(emp, nodes, 300, seed=0, layout="uniform")
    h = generate(emp, nodes, 300, seed=0, layout="hotspot")
    top = lambda os_: pd.Series([o.node for o in os_]).value_counts().iloc[:20].sum()
    assert top(h) > top(u)


def test_statistics_match(emp, nodes):
    r = compare_to_empirical(generate(emp, nodes, 300, seed=0), emp)
    assert r["service_time"] > 0.01
    assert abs(r["share_with_tw_generated"] - r["share_with_tw_empirical"]) < 0.06
