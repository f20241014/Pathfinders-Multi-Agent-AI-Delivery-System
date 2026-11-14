"""R6 robustness tests for the predictor and traffic model."""
import numpy as np
import pytest

from src.prediction.predictor import CACHE_STEPS, Predictor
from src.world.traffic_model import TrafficModel


@pytest.fixture(scope="module")
def setup():
    tm = TrafficModel.from_graph()
    return tm, Predictor(tm)


def test_start_of_sim_is_finite_and_in_range(setup):
    tm, p = setup
    for t in (0, 60, 300, 3300):
        for h in (15, 30, 60):
            v = p.predict(0, t, h)
            assert np.isfinite(v) and 1.0 <= v <= 6.0


def test_past_end_of_table_wraps_without_crash(setup):
    tm, p = setup
    t = tm.n_steps * 300 + 3600
    for h in (15, 30, 60):
        v = p.predict(5, t, h)
        assert np.isfinite(v) and 1.0 <= v <= 6.0
        assert 1.0 <= tm.actual_multiplier(5, t) <= 6.0


def test_cache_is_bounded(setup):
    tm, p = setup
    for k in range(40):
        p.predict(0, 9 * 3600 + k * 300, 15)
    assert len(p.cache) <= CACHE_STEPS


def test_cached_equals_fresh(setup):
    tm, p = setup
    t = 9 * 3600 + 288 * 300 * 3
    a = p.predict(10, t, 30)
    p.cache.clear()
    b = p.predict(10, t, 30)
    assert a == b


def test_all_edges_valid_at_rush_hour(setup):
    tm, p = setup
    step = p.refresh(9 * 3600 + 288 * 300 * 5)
    arr = p.cache[step]
    assert arr.shape == (tm.mult.shape[0], 3)
    assert np.isfinite(arr).all() and arr.min() >= 1.0 and arr.max() <= 6.0


def test_bad_horizons_raise(setup):
    tm, p = setup
    for h in (0, 10, 45, 120, None):
        with pytest.raises(ValueError):
            p.predict(0, 9 * 3600, h)


def test_unknown_edge_in_uv_lookup_raises_keyerror(setup):
    tm, p = setup
    with pytest.raises(KeyError):
        tm.actual_multiplier_uv("no_such_node", "other", 0)
