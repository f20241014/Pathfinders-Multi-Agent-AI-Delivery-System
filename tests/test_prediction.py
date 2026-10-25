"""R6 tests: splits, traffic model, predictor."""
import numpy as np
from src.prediction.data_prep import prepare_ratio
from src.world.traffic_model import TrafficModel, SIM_START
from src.prediction.predictor import Predictor
import pandas as pd


def test_splits_are_disjoint_and_ordered():
    _, train, val, test = prepare_ratio()
    assert train.index.max() < val.index.min()
    assert val.index.max() < test.index.min()


def test_ratio_range():
    ratio, *_ = prepare_ratio()
    v = ratio.stack()
    assert v.min() >= 0.05 and v.max() <= 1.0


def test_sim_days_inside_test_period():
    _, _, _, test = prepare_ratio()
    assert pd.Timestamp(SIM_START) >= test.index.min()


def test_traffic_model_multipliers_at_least_one():
    tm = TrafficModel.from_graph()
    assert tm.mult.min() >= 1.0


def test_traffic_model_deterministic():
    a = TrafficModel.from_graph(seed=7)
    b = TrafficModel.from_graph(seed=7)
    assert np.array_equal(a.mult, b.mult)


def test_predictor_outputs():
    tm = TrafficModel.from_graph()
    p = Predictor(tm)
    for h in (15, 30, 60):
        v = p.predict(0, 9 * 3600, h)
        assert 1.0 <= v <= 6.0


def test_zone_count_is_sensible():
    from src.world.edge_table import load_edge_table
    edges, classes, zones = load_edge_table()
    assert 20 <= len(set(zones)) <= 150


def test_predictor_rejects_bad_horizon():
    import pytest
    p = Predictor(TrafficModel.from_graph())
    with pytest.raises(ValueError):
        p.predict(0, 9 * 3600, 20)


def test_predictor_never_peeks_at_future():
    import copy
    tm = TrafficModel.from_graph()
    t = 9 * 3600 + 7 * 288 * 300
    step = int(t // 300)
    edges = [0, 100, 2000, 5000]
    before = [[Predictor(tm).predict(e, t, h) for h in (15, 30, 60)] for e in edges]
    tm2 = copy.copy(tm)
    m = tm.mult.copy()
    m[:, step + 1:] = np.clip(m[:, step + 1:] * 2, 1.0, 6.0)
    tm2.mult = m
    after = [[Predictor(tm2).predict(e, t, h) for h in (15, 30, 60)] for e in edges]
    assert np.allclose(before, after)
