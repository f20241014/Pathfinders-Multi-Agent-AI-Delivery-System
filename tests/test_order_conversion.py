
from src.data.orders_from_amazon import convert_to_sim_orders
from src.data.orders_from_amazon import GeneratedOrder


def test_order_conversion():
    generated = [{
        "id": "O1",
        "node": "12345",
        "demand": 15000.0,
        "priority": 1,
        "tw_start": -1.0,
        "tw_end": -1.0,
        "service_time": 60.0,
        "release_time": 0.0
    }]

    result = convert_to_sim_orders(generated)

    assert len(result) == 1
    assert isinstance(result[0], GeneratedOrder)
    assert isinstance(result[0].node, int)
