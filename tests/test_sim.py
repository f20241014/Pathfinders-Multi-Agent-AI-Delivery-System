# tests/test_sim.py
import pytest
import numpy as np
import networkx as nx
import sys
import os
from src.sim.world import FakeWorld, World
from src.sim.models import Vehicle, Order, Event
from src.sim.environment import DeliverySimEnvironment
from src.sim.events import EventGenerator
from src.sim.logger import SimulationLogger

@pytest.fixture
def sample_graph():
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, free_flow_time=10.0, length=100.0)
    G.add_edge(2, 3, free_flow_time=10.0, length=100.0)
    G.add_edge(3, 4, free_flow_time=10.0, length=100.0)
    return G

def test_reproducibility(sample_graph, tmp_path):
    world1 = FakeWorld(sample_graph)
    config1 = {
        "run_id": "repro_run", "seed": 42, "log_path": str(tmp_path / "r1.jsonl"),
        "disruption_rate_per_hour": 10.0
    }
    env1 = DeliverySimEnvironment(world1, config1)
    env1.run(duration_seconds=3600.0)

    world2 = FakeWorld(sample_graph)
    config2 = {
        "run_id": "repro_run", "seed": 42, "log_path": str(tmp_path / "r2.jsonl"),
        "disruption_rate_per_hour": 10.0
    }
    env2 = DeliverySimEnvironment(world2, config2)
    env2.run(duration_seconds=3600.0)

    with open(tmp_path / "r1.jsonl") as f1, open(tmp_path / "r2.jsonl") as f2:
        assert f1.read() == f2.read()

def test_logger_append_no_overwrite(tmp_path):
    log_file = str(tmp_path / "append_test.jsonl")
    logger1 = SimulationLogger(output_path=log_file)
    logger1.log("run1", "ind", 42, "scen", 5.0, 1.0, "v1", "start", {})

    logger2 = SimulationLogger(output_path=log_file)
    logger2.log("run1", "ind", 42, "scen", 5.0, 2.0, "v1", "stop", {})

    with open(log_file) as f:
        lines = f.readlines()
        assert len(lines) == 2

def test_fixed_traversal_time_on_entry(sample_graph, tmp_path):
    world = FakeWorld(sample_graph, speed_mps=10.0)
    config = {"run_id": "trav", "seed": 42, "log_path": str(tmp_path / "trav.jsonl")}
    env = DeliverySimEnvironment(world, config)

    v = Vehicle(id="V1", depot_node=1, capacity=50.0, current_node=1, remaining_route=[2, 3])
    env.add_vehicle(v, [])

    # Add spike at t=5 while vehicle is traversing edge (1, 2)
    world.add_disruption(Event(t=5.0, type="traffic_spike", target="1,2", magnitude=3.0, duration=600.0))
    env.run(duration_seconds=30.0)

    # Vehicle enters edge 1->2 at t=0 (time=10s). Reaches node 2 at t=10s despite spike at t=5s.
    assert v.current_node == 3

def test_closure_and_wait(sample_graph, tmp_path):
    world = FakeWorld(sample_graph, speed_mps=10.0)
    world.add_disruption(Event(t=0.0, type="closure", target="1,2", magnitude=1.0, duration=30.0))
    
    assert world.is_blocked(1, 2, 10.0) is True
    assert world.edge_time(1, 2, 10.0) == float("inf")
    assert world.is_blocked(1, 2, 35.0) is False

def test_stop_service_and_capacity(sample_graph, tmp_path):
    world = FakeWorld(sample_graph, speed_mps=10.0)
    config = {"run_id": "stop", "seed": 42, "log_path": str(tmp_path / "stop.jsonl")}
    env = DeliverySimEnvironment(world, config)

    order = Order(id="O1", node=2, demand=100.0, priority=1, tw_start=0.0, tw_end=1000.0, service_time=50.0, release_time=0.0)
    v = Vehicle(id="V1", depot_node=1, capacity=50.0, current_node=1, remaining_route=[2])
    
    env.add_vehicle(v, [order])
    env.run(duration_seconds=100.0)

    # Over-capacity load should not be served
    assert v.load == 0.0

def test_lazy_imports_no_torch():
    from src.sim import DeliverySimEnvironment, Vehicle, Order, Event, World
    assert "torch" not in sys.modules