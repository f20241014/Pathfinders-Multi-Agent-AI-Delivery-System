"""Unit tests for the simulation core (R1) on a small toy graph.

Toy graph at 10 m/s: 1->2 takes 10 s, 2->3 takes 15 s, 3->4 (key 1) takes 5 s.
Default start is 06:00 = 21600 s.
"""
import json
import math

import networkx as nx
import numpy as np
import pytest
import simpy

from src.sim.environment import DeliverySimEnvironment
from src.sim.events import EVENT_PROBS, EVENT_TYPES, EventGenerator
from src.sim.interfaces import Route
from src.sim.logger import SimulationLogger
from src.sim.models import Event, Order, Vehicle
from src.sim.world import FakeWorld, World

START = 21600.0
LOG_KEYS = ["run_id", "mode", "seed", "scenario", "rate", "t", "agent_id", "event", "payload"]


@pytest.fixture
def toy_graph():
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, key=0, length=100.0)
    G.add_edge(2, 3, key=0, length=150.0)
    G.add_edge(3, 4, key=1, length=50.0)
    return G


def make_env(world, tmp_path, **extra):
    config = {"run_id": "test", "seed": 42, "log_path": str(tmp_path / "log.jsonl")}
    config.update(extra)
    return DeliverySimEnvironment(world, config)


def vehicle(route, start=1, capacity=50.0):
    return Vehicle(id="V1", depot_node=start, capacity=capacity,
                   current_node=start, remaining_route=list(route))


def read_log(env):
    with open(env.log_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def events(rows, name):
    return [r for r in rows if r["event"] == name]


# ----------------------------------------------------------------------
# World
# ----------------------------------------------------------------------
def test_closure_wait_at_default_start(toy_graph, tmp_path):
    world = FakeWorld(toy_graph)
    world.add_disruption(1, 2, 0, expiry_t_seconds=START + 130)
    env = make_env(world, tmp_path)               # no start_time_s: default 06:00
    env.add_vehicle(vehicle([2]), [])
    env.run(600)
    rows = read_log(env)
    waits = events(rows, "blocked_wait")
    assert [w["t"] for w in waits] == [START, START + 60, START + 120]
    assert events(rows, "edge_enter")[0]["t"] == START + 180
    assert events(rows, "edge_exit")[0]["t"] == START + 190


def test_closure_and_spike_with_future_start(toy_graph):
    world = FakeWorld(toy_graph)
    world.add_disruption(1, 2, 0, expiry_t_seconds=22100, start_t_seconds=22000)
    world.add_spike(2, 3, 0, 2.0, expiry_t_seconds=22100, start_t_seconds=22000)
    assert not world.is_blocked(1, 2, 0, 21999)
    assert world.is_blocked(1, 2, 0, 22000)
    assert not world.is_blocked(1, 2, 0, 22100)
    assert world.spike_multiplier(2, 3, 0, 21999) == 1.0
    assert world.spike_multiplier(2, 3, 0, 22000) == 2.0
    assert world.spike_multiplier(2, 3, 0, 22100) == 1.0


def test_spike_slows_road_then_expires(toy_graph):
    world = FakeWorld(toy_graph)
    world.add_spike(1, 2, 0, 2.0, expiry_t_seconds=22000)
    world.add_spike(1, 2, 0, 1.5, expiry_t_seconds=21700)
    assert world.edge_time(1, 2, 0, START) == pytest.approx(30.0)   # 10 x 2 x 1.5
    assert world.edge_time(1, 2, 0, 21800) == pytest.approx(20.0)
    assert world.edge_time(1, 2, 0, 22000) == pytest.approx(10.0)


@pytest.mark.parametrize("cls", [World, FakeWorld])
def test_missing_edge_raises_key_error(toy_graph, cls):
    world = cls(toy_graph)
    for call in (
        lambda: world.free_flow_time(1, 99, 0),
        lambda: world.is_blocked(1, 99, 0, START),
        lambda: world.edge_time(1, 99, 0, START),
        lambda: world.spike_multiplier(1, 99, 0, START),
        lambda: world.edge_key(1, 99),
        lambda: world.edge_time(1, 2, 5, START),       # wrong key
    ):
        with pytest.raises(KeyError):
            call()


def test_free_flow_time_fallbacks(caplog):
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, key=0, free_flow_time=7.0, length=999.0)
    G.add_edge(2, 3, key=0, length=50.0)
    G.add_edge(3, 4, key=0, weight=30.0)
    G.add_edge(4, 5, key=0)
    G.add_edge(5, 6, key=0)
    world = FakeWorld(G, speed_mps=10.0)
    assert world.free_flow_time(1, 2) == 7.0
    assert world.free_flow_time(2, 3) == 5.0
    assert world.free_flow_time(3, 4) == 3.0
    with caplog.at_level("WARNING"):
        assert world.free_flow_time(4, 5) == 10.0
        assert world.free_flow_time(5, 6) == 10.0
    assert len([r for r in caplog.records if "no free_flow_time" in r.message]) == 1


def test_edge_key_picks_fastest_parallel_road():
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, key=0, length=500.0)
    G.add_edge(1, 2, key=1, length=100.0)
    world = FakeWorld(G)
    assert world.edge_key(1, 2) == 1
    assert world.cost_fn_at(START)(1, 2, {}) == pytest.approx(10.0)


def test_cost_fn_at_blocks_closed_road(toy_graph):
    world = FakeWorld(toy_graph)
    world.add_disruption(1, 2, 0, expiry_t_seconds=22000)
    cost = world.cost_fn_at(START)
    assert cost(1, 2) == math.inf
    assert cost(2, 3) == pytest.approx(15.0)
    assert world.cost_fn_at(22000)(1, 2) == pytest.approx(10.0)


class StubTraffic:
    edge_index = {("1", "2"): 0}

    def actual_multiplier_uv(self, u, v, t):
        if (u, v) not in self.edge_index:
            raise KeyError((u, v))
        return 2.0


class StubPredictor:
    def predicted_time(self, edge_idx, t, horizon_min, free_flow):
        return free_flow * 3.0


def test_traffic_model_and_predictor_wiring(toy_graph):
    world = World(toy_graph, traffic_model=StubTraffic(), predictor=StubPredictor())
    assert world.edge_time(1, 2, 0, START) == pytest.approx(20.0)   # model x2
    assert world.edge_time(2, 3, 0, START) == pytest.approx(15.0)   # KeyError -> 1.0
    assert world.predicted_time(1, 2, START) == pytest.approx(30.0)
    assert world.predicted_time(2, 3, START) == pytest.approx(15.0)  # unknown edge
    assert FakeWorld(toy_graph).predicted_time(1, 2, START) == pytest.approx(10.0)


# ----------------------------------------------------------------------
# Vehicle movement
# ----------------------------------------------------------------------
def test_route_starting_at_current_node(toy_graph, tmp_path):
    env = make_env(FakeWorld(toy_graph), tmp_path)
    env.add_vehicle(vehicle([1, 2, 3]), [])
    env.run(600)
    rows = read_log(env)
    assert [r["payload"]["edge"] for r in events(rows, "edge_enter")] == [[1, 2, 0], [2, 3, 0]]
    assert all(r["agent_id"] == "V1" for r in events(rows, "edge_enter"))


def test_road_with_key_one(toy_graph, tmp_path):
    env = make_env(FakeWorld(toy_graph), tmp_path)
    env.add_vehicle(vehicle([2, 3, 4]), [])
    env.run(600)
    rows = read_log(env)
    assert events(rows, "edge_enter")[-1]["payload"]["edge"] == [3, 4, 1]
    assert events(rows, "edge_exit")[-1]["payload"] == {"node": 4}
    assert events(rows, "edge_exit")[-1]["t"] == START + 30


def test_waits_at_closure_then_continues(toy_graph, tmp_path):
    world = FakeWorld(toy_graph)
    world.add_disruption(2, 3, 0, expiry_t_seconds=START + 100, start_t_seconds=START + 5)
    env = make_env(world, tmp_path)
    env.add_vehicle(vehicle([2, 3]), [])
    env.run(600)
    rows = read_log(env)
    assert [w["t"] for w in events(rows, "blocked_wait")] == [START + 10, START + 70]
    enter = events(rows, "edge_enter")[-1]
    assert enter["t"] == START + 130 and enter["payload"]["edge"] == [2, 3, 0]
    assert events(rows, "edge_exit")[-1]["t"] == START + 145


def test_spike_slows_vehicle(toy_graph, tmp_path):
    world = FakeWorld(toy_graph)
    world.add_spike(1, 2, 0, 3.0, expiry_t_seconds=START + 3600)
    env = make_env(world, tmp_path)
    env.add_vehicle(vehicle([2]), [])
    env.run(600)
    rows = read_log(env)
    assert events(rows, "edge_enter")[0]["payload"]["expected_duration"] == pytest.approx(30.0)
    assert events(rows, "edge_exit")[0]["t"] == START + 30


# ----------------------------------------------------------------------
# Orders
# ----------------------------------------------------------------------
def deliver(toy_graph, tmp_path, order, route=(2,), capacity=50.0, duration=3600):
    env = make_env(FakeWorld(toy_graph), tmp_path)
    env.add_vehicle(vehicle(route, capacity=capacity), [order])
    env.run(duration)
    return read_log(env)


def test_delivery_time(toy_graph, tmp_path):
    order = Order(id="O1", node=2, demand=10, tw_start=START, tw_end=30000, service_time=300)
    rows = deliver(toy_graph, tmp_path, order)
    done = events(rows, "order_delivered")
    assert len(done) == 1 and done[0]["t"] == START + 10 + 300
    assert done[0]["agent_id"] == "V1" and done[0]["payload"]["order_id"] == "O1"


def test_order_at_start_node(toy_graph, tmp_path):
    order = Order(id="O1", node=1, demand=10, tw_start=START, tw_end=30000, service_time=300)
    rows = deliver(toy_graph, tmp_path, order)
    assert events(rows, "order_delivered")[0]["t"] == START + 300
    assert events(rows, "edge_enter")[0]["t"] == START + 300


def test_early_arrival_waits_for_tw_start(toy_graph, tmp_path):
    order = Order(id="O1", node=2, demand=10, tw_start=22000, tw_end=30000, service_time=300)
    rows = deliver(toy_graph, tmp_path, order)
    assert events(rows, "order_delivered")[0]["t"] == 22000 + 300


def test_release_time_delays_service(toy_graph, tmp_path):
    order = Order(id="O1", node=2, demand=10, tw_start=START, tw_end=30000,
                  service_time=300, release_time=22500)
    rows = deliver(toy_graph, tmp_path, order)
    assert events(rows, "order_delivered")[0]["t"] == 22500 + 300


def test_time_window_missed(toy_graph, tmp_path):
    order = Order(id="O1", node=2, demand=10, tw_start=20000, tw_end=START + 5)
    rows = deliver(toy_graph, tmp_path, order)
    failed = events(rows, "order_failed")
    assert len(failed) == 1 and failed[0]["payload"]["reason"] == "time_window_missed"
    assert failed[0]["t"] == START + 10
    assert not events(rows, "order_delivered")


def test_invalid_time_window(toy_graph, tmp_path):
    order = Order(id="O1", node=2, demand=10, tw_start=START, tw_end=25000,
                  release_time=26000)
    rows = deliver(toy_graph, tmp_path, order)
    assert events(rows, "order_failed")[0]["payload"]["reason"] == "invalid_time_window"


def test_capacity_blocked_then_order_failed(toy_graph, tmp_path):
    order = Order(id="O1", node=2, demand=100, tw_start=START, tw_end=30000)
    rows = deliver(toy_graph, tmp_path, order, route=(2, 3))
    blocked = events(rows, "capacity_blocked")
    assert len(blocked) == 1 and blocked[0]["payload"]["capacity"] == 50.0
    failed = events(rows, "order_failed")
    assert len(failed) == 1
    assert failed[0]["payload"]["reason"] == "capacity_exceeded_unservable"
    assert failed[0]["t"] == START + 25               # at the end of the route


def test_order_not_on_route(toy_graph, tmp_path):
    order = Order(id="O1", node=3, demand=10, tw_start=START, tw_end=30000)
    rows = deliver(toy_graph, tmp_path, order, route=(2,))
    failed = events(rows, "order_failed")
    assert len(failed) == 1 and failed[0]["payload"]["reason"] == "not_on_route"


def test_add_order(toy_graph, tmp_path):
    env = make_env(FakeWorld(toy_graph), tmp_path)
    order = Order(id="O_R3", node=2, demand=5.0)
    env.add_order(order)
    env.add_order(order)
    assert [o.id for o in env.orders] == ["O_R3"]


def test_vehicle_current_load_and_defaults():
    v = Vehicle(id="V1", depot_node=1, capacity=10.0, current_node=1)
    assert v.current_load == 0.0
    v.load = 4.0
    assert v.current_load == 4.0
    assert v.allowed_road_classes is None and v.current_edge is None


def test_route_order_ids():
    assert Route([1, 2], [0.0, 10.0]).order_ids == []
    assert Route([1, 2], [0.0, 10.0], order_ids=["O1"]).order_ids == ["O1"]


# ----------------------------------------------------------------------
# Events (D11)
# ----------------------------------------------------------------------
def run_generator(toy_graph, rate, duration, seed=0):
    env = simpy.Environment()
    world = FakeWorld(toy_graph)
    received = []
    gen = EventGenerator(env, np.random.default_rng(seed), world, received.append)
    env.process(gen.schedule_disruptions(rate, duration))
    env.run(until=duration)
    return world, received


def test_d11_mix(toy_graph):
    _, received = run_generator(toy_graph, rate=3600.0, duration=2000.0)
    assert 1800 < len(received) < 2200
    kinds = [e.payload["type"] if e.event_type == "disruption" else "new_order"
             for e in received]
    for kind, p in zip(EVENT_TYPES, EVENT_PROBS):
        assert abs(kinds.count(kind) / len(kinds) - p) < 0.05


def test_disruptions_change_the_world(toy_graph):
    world, received = run_generator(toy_graph, rate=20.0, duration=7200.0)
    road = [e for e in received if e.event_type == "disruption"]
    assert {e.payload["type"] for e in road} == {"closure", "traffic_spike"}
    for e in road:
        u, v, k = e.payload["edge"]
        p = e.payload
        assert 600 <= p["duration"] <= 1800 and p["expiry"] == pytest.approx(e.t + p["duration"])
        if p["type"] == "closure":
            assert p["magnitude"] is None
            assert world.is_blocked(u, v, k, e.t)
        else:
            assert 1.2 <= p["magnitude"] <= 3.0
            assert world.spike_multiplier(u, v, k, e.t) >= p["magnitude"]
    orders = [e for e in received if e.event_type == "new_order"]
    assert [e.payload["order_id"] for e in orders] == [f"dyn_{i + 1}" for i in range(len(orders))]
    assert all(e.payload["release_time"] == e.t for e in orders)


def test_subscribers_get_events(toy_graph, tmp_path):
    env = make_env(FakeWorld(toy_graph), tmp_path, disruption_rate_per_hour=20.0)
    got = []
    env.subscribe(got.append)
    env.run(3600)
    rows = read_log(env)
    logged = [r for r in rows if r["event"] in ("disruption", "new_order")]
    assert got and all(isinstance(e, Event) for e in got)
    assert len(got) == len(logged)
    assert [round(e.t, 2) for e in got] == [r["t"] for r in logged]


def test_seeded_reproducibility(toy_graph, tmp_path):
    def run(seed, name):
        env = DeliverySimEnvironment(FakeWorld(toy_graph), {
            "run_id": "repro", "seed": seed, "disruption_rate_per_hour": 10.0,
            "log_path": str(tmp_path / name),
        })
        env.add_vehicle(vehicle([2, 3]), [])
        env.run(3600)
        return (tmp_path / name).read_text(encoding="utf-8")

    assert run(42, "a.jsonl") == run(42, "b.jsonl")
    assert run(42, "a.jsonl") != run(7, "c.jsonl")


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
def test_log_has_nine_keys_in_order(toy_graph, tmp_path):
    env = make_env(FakeWorld(toy_graph), tmp_path, mode="centralized",
                   scenario="toy", disruption_rate_per_hour=5.0)
    env.add_vehicle(vehicle([2]), [])
    env.run(1800)
    rows = read_log(env)
    assert all(list(r.keys()) == LOG_KEYS for r in rows)
    assert rows[0]["event"] == "sim_start" and rows[0]["t"] == START
    assert rows[-1]["event"] == "sim_complete" and rows[-1]["t"] == START + 1800
    assert events(rows, "edge_exit")[0]["payload"] == {"node": 2}
    assert rows[0]["mode"] == "centralized" and rows[0]["scenario"] == "toy"
    assert rows[0]["rate"] == 5.0 and rows[0]["seed"] == 42 and rows[0]["run_id"] == "test"


def test_default_log_path(toy_graph, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = DeliverySimEnvironment(FakeWorld(toy_graph), {"run_id": "abc"})
    env.run(10)
    assert (tmp_path / "logs" / "abc.jsonl").exists()


def test_logger_overwrites_and_rounds(tmp_path):
    path = str(tmp_path / "x.jsonl")
    SimulationLogger(path, "r", "independent", 1, "s", 0.0).log("a", 1.23456, {})
    logger = SimulationLogger(path, "r", "independent", 1, "s", 0.0)
    logger.log("b", 2.0, {"k": 1}, agent_id="V9")
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    assert len(rows) == 1 and rows[0]["event"] == "b" and rows[0]["agent_id"] == "V9"
    SimulationLogger(path, "r", "independent", 1, "s", 0.0, file_mode="a").log("c", 1.23456, {})
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    assert len(rows) == 2 and rows[1]["t"] == 1.23


def test_logger_path_without_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    SimulationLogger("plain.jsonl", "r", "independent", 1, "s", 0.0).log("e", 1.0, {})
    assert (tmp_path / "plain.jsonl").exists()
