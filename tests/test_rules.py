
from types import SimpleNamespace

from src.kr.rules import feasible


def make_vehicle(capacity=100, current_load=0):
    return SimpleNamespace(
        id="V1",
        capacity=capacity,
        current_load=current_load
    )


def make_order(
    order_id,
    demand,
    priority=1,
    tw_start=None,
    tw_end=None,
    service_time=30,
    release_time=0
):
    return SimpleNamespace(
        id=order_id,
        demand=demand,
        priority=priority,
        tw_start=tw_start,
        tw_end=tw_end,
        service_time=service_time,
        release_time=release_time
    )


def test_capacity_passes():
    vehicle = make_vehicle()
    orders = [
        make_order("O1", 40),
        make_order("O2", 50)
    ]

    result, trace = feasible(vehicle, orders)

    assert result is True


def test_capacity_fails():
    vehicle = make_vehicle()
    orders = [
        make_order("O1", 60),
        make_order("O2", 50)
    ]

    result, trace = feasible(vehicle, orders)

    assert result is False


def test_current_load_is_included():
    vehicle = make_vehicle(capacity=100, current_load=70)
    orders = [make_order("O1", 40)]

    result, trace = feasible(vehicle, orders)

    assert result is False


def test_missing_time_window_is_allowed():
    vehicle = make_vehicle()
    orders = [make_order("O1", 40)]

    result, trace = feasible(vehicle, orders)

    assert result is True


def test_invalid_time_window_fails():
    vehicle = make_vehicle()
    orders = [
        make_order("O1", 40, tw_start=20, tw_end=10)
    ]

    result, trace = feasible(vehicle, orders)

    assert result is False


def test_negative_demand_fails():
    vehicle = make_vehicle()
    orders = [make_order("O1", -10)]

    result, trace = feasible(vehicle, orders)

    assert result is False


def test_negative_service_time_fails():
    vehicle = make_vehicle()
    orders = [
        make_order("O1", 20, service_time=-5)
    ]

    result, trace = feasible(vehicle, orders)

    assert result is False


from src.kr.rules import road_allowed


def test_residential_road_allowed():
    assert road_allowed(None, "residential") is True


def test_primary_road_allowed():
    assert road_allowed(None, "primary") is True


def test_motorway_restricted():
    assert road_allowed(None, "motorway") is False


def test_unknown_road_rejected():
    assert road_allowed(None, "unknown_road") is False


def test_link_road_class():
    assert road_allowed(None, "primary_link") is True

