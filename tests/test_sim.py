import pytest
import networkx as nx
from src.sim.models import Order, Vehicle
from src.sim.world import FakeWorld
from src.sim.environment import DeliverySimEnvironment


@pytest.fixture
def sample_graph():
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, key=0, weight=10.0, road_class="primary")
    G.add_edge(2, 3, key=0, weight=15.0, road_class="secondary")
    return G


def test_reproducibility(sample_graph, tmp_path):
    world1 = FakeWorld(sample_graph)
    config1 = {
        "run_id": "repro_run",
        "seed": 42,
        "log_path": str(tmp_path / "r1.jsonl"),
        "disruption_rate_per_hour": 10.0,
    }
    env1 = DeliverySimEnvironment(world1, config1)
    env1.run(duration_seconds=3600.0)

    world2 = FakeWorld(sample_graph)
    config2 = {
        "run_id": "repro_run",
        "seed": 42,
        "log_path": str(tmp_path / "r2.jsonl"),
        "disruption_rate_per_hour": 10.0,
    }
    env2 = DeliverySimEnvironment(world2, config2)
    env2.run(duration_seconds=3600.0)

    with open(tmp_path / "r1.jsonl") as f1, open(tmp_path / "r2.jsonl") as f2:
        assert f1.read() == f2.read()


def test_fixed_traversal_cost(sample_graph, tmp_path):
    world = FakeWorld(sample_graph, speed_mps=10.0)
    config = {"run_id": "trav", "seed": 42, "log_path": str(tmp_path / "trav.jsonl")}
    env = DeliverySimEnvironment(world, config)

    v = Vehicle(id="V1", depot_node=1, capacity=10.0, current_node=1, remaining_route=[2])
    env.add_vehicle(v, [])
    env.run(duration_seconds=100.0)

    assert v.current_node == 2


def test_disruption_injection(sample_graph, tmp_path):
    world = FakeWorld(sample_graph)
    config = {
        "run_id": "disrupt",
        "seed": 42,
        "log_path": str(tmp_path / "disrupt.jsonl"),
        "disruption_rate_per_hour": 20.0,
    }
    env = DeliverySimEnvironment(world, config)
    env.run(duration_seconds=3600.0)

    with open(tmp_path / "disrupt.jsonl") as f:
        content = f.read()
        assert "disruption" in content


def test_stop_service_and_capacity(sample_graph, tmp_path):
    world = FakeWorld(sample_graph, speed_mps=10.0)
    config = {"run_id": "stop", "seed": 42, "log_path": str(tmp_path / "stop.jsonl")}
    env = DeliverySimEnvironment(world, config)

    order = Order(
        id="O1",
        node=2,
        demand=100.0,
        priority=1,
        tw_start=0.0,
        tw_end=1000.0,
        service_time=50.0,
        release_time=0.0,
    )
    v = Vehicle(id="V1", depot_node=1, capacity=50.0, current_node=1, remaining_route=[2])

    env.add_vehicle(v, [order])
    env.run(duration_seconds=100.0)

    with open(tmp_path / "stop.jsonl") as f:
        content = f.read()
        assert "capacity_blocked" in content
