"""Integration tests for the simulation core on R2's real Secunderabad graph."""
import json
import math
from pathlib import Path

import pytest
import yaml

pytest.importorskip("osmnx")

from src.search.astar import astar  # noqa: E402
from src.search.heuristics import make_heuristic  # noqa: E402
from src.sim.environment import DeliverySimEnvironment  # noqa: E402
from src.sim.run import assign_orders, build_order, build_vehicle, run_from_config  # noqa: E402
from src.sim.scenarios import make_demo_config  # noqa: E402
from src.sim.world import World  # noqa: E402
from src.world.graph_loader import load_road_graph  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "data" / "processed" / "secunderabad.graphml"
CONFIG = ROOT / "configs" / "sim_default.yaml"
START = 21600.0

pytestmark = pytest.mark.skipif(not MAP.exists(), reason="real graph not available")


@pytest.fixture(scope="module")
def G():
    return load_road_graph("secunderabad")


@pytest.fixture
def config(tmp_path):
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["log_path"] = str(tmp_path / "run.jsonl")
    return cfg


def read_log(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def run_env(world, cfg):
    env = DeliverySimEnvironment(world, cfg)
    vehicles = [build_vehicle(v) for v in cfg["vehicles"]]
    orders = [build_order(o) for o in cfg["orders"]]
    assignment = assign_orders(vehicles, orders)
    for v in vehicles:
        env.add_vehicle(v, assignment[v.id])
    env.run(cfg["duration_seconds"])
    return read_log(env.log_path)


def test_from_defaults_loads_real_graph():
    world = World.from_defaults(str(MAP))
    assert world.graph().number_of_nodes() == 2377
    assert world.G is world.graph()


def test_edge_times_equal_free_flow_and_vary(G):
    world = World(G)
    times = []
    for u, v, k, data in G.edges(keys=True, data=True):
        t = world.edge_time(u, v, START, key=k)
        assert t == pytest.approx(data["free_flow_time"])
        times.append(round(t, 1))
    assert len(set(times)) > 100


def test_roads_with_nonzero_key(G):
    world = World(G)
    odd = [(u, v, k) for u, v, k in G.edges(keys=True) if k != 0]
    assert len(odd) == 5
    for u, v, k in odd:
        assert world.edge_key(u, v) == k
        assert math.isfinite(world.edge_time(u, v, START, key=k))


def test_astar_avoids_closed_road(G, config):
    world = World(G)
    route = config["vehicles"][0]["route"]
    source, target = route[0], route[-1]
    h = make_heuristic(G)
    before = astar(G, source, target, cost_fn=world.cost_fn_at(START), heuristic=h)
    assert before.path
    mid = len(before.path) // 2
    u, v = before.path[mid], before.path[mid + 1]
    world.add_disruption(u, v, world.edge_key(u, v), expiry_t_seconds=START + 3600)
    after = astar(G, source, target, cost_fn=world.cost_fn_at(START), heuristic=h)
    assert after.path and after.path[0] == source and after.path[-1] == target
    assert (u, v) not in set(zip(after.path, after.path[1:]))
    assert after.cost >= before.cost
    # After the closure expires the original path is available again.
    later = astar(G, source, target, cost_fn=world.cost_fn_at(START + 3600), heuristic=h)
    assert later.cost == pytest.approx(before.cost)


def test_default_config_end_to_end(G, config):
    log_path = run_from_config(config)
    rows = read_log(log_path)
    enters = [r for r in rows if r["event"] == "edge_enter"]
    assert len(enters) == 56
    assert all(G.has_edge(*r["payload"]["edge"]) for r in enters)
    delivered = [r for r in rows if r["event"] == "order_delivered"]
    assert sorted(r["payload"]["order_id"] for r in delivered) == ["O1", "O2"]
    assert not [r for r in rows if r["event"] == "order_failed"]
    assert rows[0]["event"] == "sim_start" and rows[-1]["event"] == "sim_complete"
    assert all(len(r) == 9 for r in rows)


def test_vehicle_waits_at_closure_on_real_map(G, config):
    world = World(G)
    route = config["vehicles"][0]["route"]
    u, v = route[0], route[1]
    world.add_disruption(u, v, world.edge_key(u, v), expiry_t_seconds=START + 120)
    config["disruption_rate_per_hour"] = 0.0
    rows = run_env(world, config)
    waits = [r for r in rows if r["event"] == "blocked_wait"]
    assert [w["t"] for w in waits] == [START, START + 60]
    first_enter = next(r for r in rows if r["event"] == "edge_enter")
    assert first_enter["t"] == START + 120
    assert len([r for r in rows if r["event"] == "order_delivered"]) == 2


def test_make_demo_config_runs(G, tmp_path):
    cfg = make_demo_config(World(G))
    cfg["log_path"] = str(tmp_path / "demo.jsonl")
    rows = run_env(World(G), cfg)
    assert rows[-1]["event"] == "sim_complete"
    assert any(r["event"] == "edge_enter" for r in rows)
    assert all(G.has_edge(*r["payload"]["edge"])
               for r in rows if r["event"] == "edge_enter")
