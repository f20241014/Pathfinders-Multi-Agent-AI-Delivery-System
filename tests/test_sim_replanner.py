"""Tests for src/search/sim_replanner.py (R7, Week 3): D* Lite inside R1's sim.

Grid world, 3 x 3, every road 100 m at 10 m/s = 10 s. Node = 3 * row + col:

    0 - 1 - 2
    |   |   |
    3 - 4 - 5
    |   |   |
    6 - 7 - 8
"""
import json
import math
import random

import networkx as nx
import pytest

from src.search.astar import astar
from src.search.sim_replanner import (
    SimReplanner, VehicleReplanner, reroute, stops_from_route, world_cost,
)
from src.sim.environment import DeliverySimEnvironment
from src.sim.models import Event, Order, Vehicle
from src.sim.world import FakeWorld

START = 21600.0


def grid_graph(n=3):
    G = nx.MultiDiGraph()
    for r in range(n):
        for c in range(n):
            a = n * r + c
            for b in ([a + 1] if c + 1 < n else []) + ([a + n] if r + 1 < n else []):
                G.add_edge(a, b, key=0, length=100.0)
                G.add_edge(b, a, key=0, length=100.0)
    return G


@pytest.fixture
def world():
    return FakeWorld(grid_graph())


def make_env(world, tmp_path):
    return DeliverySimEnvironment(world, {
        "run_id": "r7", "seed": 1, "log_path": str(tmp_path / "log.jsonl")})


def rows(env, name=None):
    with open(env.log_path, encoding="utf-8") as f:
        out = [json.loads(line) for line in f]
    return [r for r in out if name is None or r["event"] == name]


def close_road_at(env, u, v, after_s, duration_s=3600.0):
    """SimPy process: close u -> v after after_s and announce it."""
    def proc():
        yield env.env.timeout(after_s)
        t = env.get_current_time()
        env.world.add_disruption(u, v, 0, t + duration_s, start_t_seconds=t)
        env.handle_event(Event(t, "disruption", {
            "type": "closure", "edge": [u, v, 0], "magnitude": None,
            "duration": duration_s, "expiry": t + duration_s}))
    env.env.process(proc())


# ---------------------------------------------------------------------------
# Costs from the World (D10)
# ---------------------------------------------------------------------------
def test_world_cost_free_flow_spike_and_closure(world):
    assert world_cost(world, 0, 1, START) == 10.0
    world.add_spike(0, 1, 0, 2.0, START + 100, start_t_seconds=START)
    assert world_cost(world, 0, 1, START) == 20.0
    assert world_cost(world, 0, 1, START + 100) == 10.0      # spike expired
    world.add_disruption(0, 1, 0, START + 50, start_t_seconds=START)
    assert world_cost(world, 0, 1, START) == math.inf
    assert world_cost(world, 0, 1, START + 60) == 20.0       # reopened, spike still on


def test_stops_from_route():
    assert stops_from_route([1, 2, 5, 8], {5}) == [5, 8]
    assert stops_from_route([1, 2, 5, 8], {8, 2}) == [2, 8]
    assert stops_from_route([], {3}) == []


# ---------------------------------------------------------------------------
# reroute(): the one-off call for the TODO(R7) in environment.py
# ---------------------------------------------------------------------------
def test_reroute_avoids_closed_road(world):
    world.add_disruption(1, 2, 0, START + 999, start_t_seconds=START)
    v = Vehicle("V1", 0, 10.0, current_node=0, remaining_route=[1, 2])
    new = reroute(world, v, [2], START)
    assert new[-1] == 2
    assert (1, 2) not in list(zip([0] + new, new))
    assert len(new) == 4                                      # 0-3-4-5-2 or 0-1-4-5-2


def test_reroute_returns_none_when_unreachable(world):
    for u in (1, 5):
        world.add_disruption(u, 2, 0, START + 999, start_t_seconds=START)
    v = Vehicle("V1", 0, 10.0, current_node=0)
    assert reroute(world, v, [2], START) is None


def test_to_route_has_etas_and_order_ids(world):
    vr = VehicleReplanner(world, 0, [2, 8], START, order_ids=["o1", "o2"])
    route = vr.to_route(START)
    assert route.nodes[0] == 0 and route.nodes[-1] == 8
    assert route.expected_times[0] == START
    assert route.expected_times[-1] == START + 40.0           # 4 roads x 10 s
    assert route.order_ids.count("o1") == 1 and route.order_ids[-1] == "o2"
    assert route.order_ids[route.nodes.index(2)] == "o1"


# ---------------------------------------------------------------------------
# SimReplanner inside R1's DeliverySimEnvironment
# ---------------------------------------------------------------------------
def test_without_replanner_vehicle_waits_at_closure(world, tmp_path):
    env = make_env(world, tmp_path)
    veh = Vehicle("V1", 0, 10.0, current_node=0, remaining_route=[1, 2])
    env.add_vehicle(veh, [Order("o1", 2, 1.0, service_time=0.0)])
    close_road_at(env, 1, 2, after_s=5, duration_s=600)
    env.run(2000)
    assert rows(env, "blocked_wait")                          # R1's current behaviour


def test_closure_ahead_reroutes_without_waiting(world, tmp_path):
    env = make_env(world, tmp_path)
    veh = Vehicle("V1", 0, 10.0, current_node=0)
    sr = SimReplanner(env)
    sr.register(veh, stops=[2])
    assert veh.remaining_route == [1, 2]                      # straight along row 0
    env.add_vehicle(veh, [Order("o1", 2, 1.0, service_time=0.0)])
    close_road_at(env, 1, 2, after_s=5, duration_s=600)       # vehicle is on 0 -> 1
    env.run(2000)
    assert not rows(env, "blocked_wait")
    delivered = rows(env, "order_delivered")
    assert delivered and delivered[0]["t"] == START + 40.0    # 0-1-4-5-2, no wait
    replan = rows(env, "replan")[0]
    assert replan["agent_id"] == "V1"
    assert replan["payload"]["from_node"] == 1                # end of the road it was on
    assert replan["payload"]["cpu_seconds"] >= 0
    entered = [tuple(r["payload"]["edge"][:2]) for r in rows(env, "edge_enter")]
    assert (1, 2) not in entered


def test_closure_off_route_changes_nothing(world, tmp_path):
    env = make_env(world, tmp_path)
    veh = Vehicle("V1", 0, 10.0, current_node=0)
    SimReplanner(env).register(veh, stops=[2])
    env.add_vehicle(veh, [Order("o1", 2, 1.0, service_time=0.0)])
    close_road_at(env, 6, 7, after_s=5)
    env.run(2000)
    assert rows(env, "order_delivered")[0]["t"] == START + 20.0
    assert rows(env, "replan") == []        # W5: same route, so no replan row


def test_multi_stop_vehicle_reroutes_after_first_stop(world, tmp_path):
    env = make_env(world, tmp_path)
    veh = Vehicle("V1", 0, 10.0, current_node=0)
    SimReplanner(env).register(veh, stops=[2, 8])
    env.add_vehicle(veh, [Order("o1", 2, 1.0, service_time=0.0),
                          Order("o2", 8, 1.0, service_time=0.0)])
    path_after_2 = veh.remaining_route[veh.remaining_route.index(2):]
    u, v = path_after_2[0], path_after_2[1]                   # first road of leg 2
    close_road_at(env, u, v, after_s=15)                      # while driving 1 -> 2
    env.run(2000)
    assert [r["payload"]["order_id"] for r in rows(env, "order_delivered")] == ["o1", "o2"]
    entered = [tuple(r["payload"]["edge"][:2]) for r in rows(env, "edge_enter")]
    assert (u, v) not in entered
    assert not rows(env, "blocked_wait")


def test_random_closures_vehicle_always_matches_astar(tmp_path):
    """Random closures during the run; every replan's route cost from the
    vehicle's position equals a fresh A* run on the World at that time."""
    G = grid_graph(5)
    for seed in range(15):
        rnd = random.Random(seed)
        world = FakeWorld(G.copy())
        env = make_env(world, tmp_path)
        veh = Vehicle("V1", 0, 10.0, current_node=0)
        sr = SimReplanner(env)
        stops = rnd.sample(range(1, 25), 3)
        sr.register(veh, stops=stops)
        env.add_vehicle(veh, [Order(f"o{s}", s, 1.0, service_time=0.0) for s in stops])
        edges = list(G.edges(keys=True))
        for i in range(6):
            u, v, k = rnd.choice(edges)
            close_road_at(env, u, v, after_s=7 + 13 * i, duration_s=60)

        checks = []

        def check(event):
            vr = sr.agents["V1"].replanner
            if vr.planner.done:
                return
            here = vr.position
            t = event.t

            def cost_fn(a, b, data):
                return world_cost(world, a, b, t)
            ref, at = 0.0, here
            for s in vr.planner.remaining_stops:
                ref += astar(G, at, s, cost_fn, heuristic=lambda a, b: 0.0).cost
                at = s
            got = vr.planner.path_cost()
            checks.append(math.isclose(got, ref) or got == ref == math.inf)
        env.subscribe(check)
        env.run(3000)
        assert checks and all(checks), seed
