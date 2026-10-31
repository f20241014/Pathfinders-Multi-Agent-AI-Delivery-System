
from src.data.orders_from_amazon import generate_orders, load_local_nodes


def test_generated_orders_have_valid_nodes():
    orders = generate_orders(20, seed=42)
    valid_nodes = set(load_local_nodes())

    for order in orders:
        assert str(order["node"]) in valid_nodes


def test_generated_orders_have_valid_demand():
    orders = generate_orders(20, seed=42)

    for order in orders:
        assert order["demand"] > 0


def test_generated_orders_have_valid_priority():
    orders = generate_orders(20, seed=42)

    for order in orders:
        assert order["priority"] in [1, 2, 3]
