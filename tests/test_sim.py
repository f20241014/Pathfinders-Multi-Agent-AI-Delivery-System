import os
import pytest
import networkx as nx
from src.sim.models import Order, Vehicle
from src.sim.world import World, FakeWorld
from src.sim.environment import DeliverySimEnvironment
from src.sim.logger import SimulationLogger


@pytest.fixture
def sample_graph():
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, key=0, weight=10.0, road_class="primary")
    G.add_edge(2, 3, key=0, weight=15.0, road_class="secondary")
    return G


def test_clock_alignment_and_closure_wait(sample_graph, tmp_path):
    world = FakeWorld(sample_graph, speed_mps=10.0)
    world.add_disruption(1, 2, 0, expiry_t_seconds=22200.0)
    log_file = str(tmp_path / "clock_test.jsonl")
    config = {
        "run_id": "clock_test",
        "seed": 42,
        "log_path": log_file,
        "start_time_s": 21600.0,
    }
    env = DeliverySimEnvironment(world, config)
    v = Vehicle(
        id="V1", depot_node=1, capacity=50.0, current_node=1, remaining_route=[2]
    )
    env.add_vehicle(v, [])
    env.run(duration_seconds=700.0)

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "blocked_wait" in content
        assert '"t": 21600' in content or '"t": 21600.0' in content


def test_missing_edge_raises_error(sample_graph):
    real_world = World(sample_graph)
    fake_world = FakeWorld(sample_graph)

    with pytest.raises(KeyError):
        real_world.free_flow_time(1, 99, 0)

    with pytest.raises(KeyError):
        fake_world.free_flow_time(1, 99, 0)

    with pytest.raises(KeyError):
        real_world.is_blocked(1, 99, 0, 21600.0)

    with pytest.raises(KeyError):
        fake_world.is_blocked(1, 99, 0, 21600.0)


def test_time_window_missed_emits_order_failed(sample_graph, tmp_path):
    world = FakeWorld(sample_graph, speed_mps=10.0)
    log_file = str(tmp_path / "tw_fail.jsonl")
    config = {
        "run_id": "tw_fail",
        "seed": 42,
        "log_path": log_file,
        "start_time_s": 21600.0,
    }
    env = DeliverySimEnvironment(world, config)
    order = Order(
        id="O_LATE",
        node=2,
        demand=10.0,
        tw_start=20000.0,
        tw_end=21600.0,
        service_time=10.0,
    )
    v = Vehicle(
        id="V1", depot_node=1, capacity=50.0, current_node=1, remaining_route=[2]
    )
    env.add_vehicle(v, [order])
    env.run(duration_seconds=100.0)

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "order_failed" in content
        assert "time_window_missed" in content


def test_capacity_blocked_and_retry(sample_graph, tmp_path):
    world = FakeWorld(sample_graph, speed_mps=10.0)
    log_file = str(tmp_path / "cap_test.jsonl")
    config = {
        "run_id": "cap_test",
        "seed": 42,
        "log_path": log_file,
        "start_time_s": 21600.0,
    }
    env = DeliverySimEnvironment(world, config)
    order = Order(
        id="O_HEAVY",
        node=2,
        demand=100.0,
        tw_start=21600.0,
        tw_end=30000.0,
        service_time=10.0,
    )
    v = Vehicle(
        id="V1", depot_node=1, capacity=50.0, current_node=1, remaining_route=[2]
    )
    env.add_vehicle(v, [order])
    env.run(duration_seconds=100.0)

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "capacity_blocked" in content
        assert "order_failed" in content


def test_add_order_handoff(sample_graph, tmp_path):
    world = FakeWorld(sample_graph)
    config = {
        "run_id": "handoff",
        "seed": 42,
        "log_path": str(tmp_path / "handoff.jsonl"),
    }
    env = DeliverySimEnvironment(world, config)
    order = Order(id="O_R3", node=2, demand=5.0)
    env.add_order(order)
    assert len(env.orders) == 1
    assert env.orders[0].id == "O_R3"


def test_logger_missing_dir():
    cwd = os.getcwd()
    target_file = os.path.join(cwd, "test_out_temp.jsonl")
    try:
        logger = SimulationLogger("test_out_temp.jsonl")
        logger.log("test_event", 100.0, {"data": 123})
        assert os.path.exists(target_file)
    finally:
        if os.path.exists(target_file):
            os.remove(target_file)


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

    with open(tmp_path / "r1.jsonl", encoding="utf-8") as f1, open(
        tmp_path / "r2.jsonl", encoding="utf-8"
    ) as f2:
        assert f1.read() == f2.read()