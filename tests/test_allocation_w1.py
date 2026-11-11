"""Hand-checkable Week 1 contracts and CVRP exercise."""
from src.allocation.toy_cvrp import solve_toy
from src.allocation.cost_model import VehicleState, schedule
from src.sim.models import Order, Vehicle


def test_toy_capacity_and_coverage():
    routes = solve_toy()
    assert sorted(n for r in routes for n in r if n) == [1, 2, 3, 4]
    assert all(len(r) - 2 <= 2 for r in routes)


def test_service_start_window_and_load():
    s = VehicleState(Vehicle('v', 0, 2, 0))
    o = Order('a', 1, 2, tw_start=10, tw_end=10, service_time=5)
    result = schedule(s, [o], lambda v, a, b: 2)
    assert result.feasible and result.arrivals == [10]
    assert not schedule(s, [o, Order('b', 2, 1)], lambda *args: 2).feasible
