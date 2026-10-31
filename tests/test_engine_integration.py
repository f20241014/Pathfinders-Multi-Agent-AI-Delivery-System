from types import SimpleNamespace
from src.kr.engine import run_feasibility_engine


def test_engine_rejects_restricted_road():
    vehicle = SimpleNamespace(
        id="V1",
        capacity=100,
        current_load=0
    )

    orders = [
        SimpleNamespace(
            demand=20,
            tw_start=10,
            tw_end=20,
            service_time=5,
            release_time=0,
            priority=1
        )
    ]

    result = run_feasibility_engine(
        vehicle,
        orders,
        edges=["residential", "motorway"]
    )

    assert result["feasible"] is False