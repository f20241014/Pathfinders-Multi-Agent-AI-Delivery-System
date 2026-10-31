
from types import SimpleNamespace

from src.kr.engine import run_feasibility_engine


def make_vehicle(capacity=100, current_load=0):
    return SimpleNamespace(
        id="V1",
        capacity=capacity,
        current_load=current_load
    )


def make_order(order_id, demand):
    return SimpleNamespace(
        id=order_id,
        node=10,
        demand=demand,
        priority=1,
        tw_start=None,
        tw_end=None,
        service_time=30,
        release_time=0
    )


def test_engine_accepts_feasible_orders():
    vehicle = make_vehicle()
    orders = [
        make_order("O1", 40),
        make_order("O2", 50)
    ]

    result = run_feasibility_engine(vehicle, orders)

    assert result["feasible"] is True
    assert len(result["trace"]) == 15


def test_engine_rejects_capacity_violation():
    vehicle = make_vehicle()
    orders = [
        make_order("O1", 60),
        make_order("O2", 50)
    ]

    result = run_feasibility_engine(vehicle, orders)

    assert result["feasible"] is False
    assert any(
        "REJECTED: CAPACITY" in item
        for item in result["trace"]
    )


def test_engine_explains_time_window_violation():
    vehicle = make_vehicle()
    order = make_order("O1", 30)

    order.tw_start = 20
    order.tw_end = 10

    result = run_feasibility_engine(vehicle, [order])

    assert result["feasible"] is False
    assert any(
        "REJECTED: TIME_WINDOW" in item
        for item in result["trace"]
    )
