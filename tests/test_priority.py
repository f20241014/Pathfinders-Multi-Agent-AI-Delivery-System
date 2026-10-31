
from types import SimpleNamespace
from src.kr.rules import sort_orders_by_priority


def test_high_priority_first():
    orders = [
        SimpleNamespace(id="O1", priority=3),
        SimpleNamespace(id="O2", priority=1),
        SimpleNamespace(id="O3", priority=2)
    ]

    sorted_orders = sort_orders_by_priority(orders)

    assert [o.id for o in sorted_orders] == ["O2", "O3", "O1"]
