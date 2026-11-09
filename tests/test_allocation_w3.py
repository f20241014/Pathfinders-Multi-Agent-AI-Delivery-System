"""Central solver: exact tiny costs, capacity, windows, drops and partial state."""
import pytest
from src.allocation.central_vrp import CentralVRP
from src.allocation.cost_model import schedule
from src.sim.models import Order
from test_allocation_w2 import state, distance


def solve(states, orders, **kwargs):
    return CentralVRP(distance, time_limit_s=0.05, **kwargs).resolve(states, orders)


def test_central_matches_tiny_optimum_and_cnp_messages():
    states = [state('a', 2), state('b', 2)]
    orders = [Order(str(i), i, 1, service_time=0) for i in range(1, 5)]
    rows = []
    result = solve(states, orders, emit=lambda k, p: rows.append((k, p)))
    assert not result.failed
    assert result.travel_seconds == 6  # pairs (1,2) and (3,4), open paths
    assert result.messages == len(rows) == 4
    assert all(schedule(s, result.routes[s.vehicle.id], distance).feasible for s in states)


def test_existing_load_priority_and_time_window_drops():
    s = state('a', 3)
    s.vehicle.load = 2
    orders = [Order('low', 1, 1, priority=1, service_time=0),
              Order('high', 2, 1, priority=3, service_time=0),
              Order('late', 100, 0, tw_end=1, service_time=0)]
    result = solve([s], orders)
    assert [o.id for o in result.routes['a']] == ['high']
    assert set(result.failed) == {'low', 'late'}


def test_partial_state_and_release_wait():
    s = state()
    s.vehicle.current_node = 5
    s.available_at = 20
    o = Order('o', 6, 1, release_time=30, tw_end=30, service_time=10)
    result = solve([s], [o])
    assert not result.failed and result.travel_seconds == 1
    s.vehicle.current_edge = (0, 5, 0)
    with pytest.raises(ValueError, match='next node'):
        solve([s], [o])


def test_unreachable_empty_and_duplicate():
    o = Order('o', 9, 1)
    result = CentralVRP(lambda *args: float('inf'), 0.05).resolve([state()], [o])
    assert result.failed == ['o']
    assert CentralVRP(distance).resolve([], [o]).failed == ['o']
    with pytest.raises(ValueError, match='duplicate order'):
        solve([state()], [o, o])
