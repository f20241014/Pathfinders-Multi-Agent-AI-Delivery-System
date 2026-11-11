"""Tests for src/sim/agent_planner.py (R7, Week 4): agent replanning on world
change, independent mode, and the trigger_enabled toggle, inside R1's sim.

Plan's Definition of Done for R7, checked here:
* a closure on the current path triggers a reroute; no path is handled
  without crashing;
* independent mode logs zero negotiation messages;
* replan CPU time is logged for every replan.

Grid world 3 x 3 (node = 3 * row + col), every road 100 m at 10 m/s = 10 s.
"""
import json
import math
import random

import networkx as nx
import pytest

from src.search.astar import astar
from src.sim.agent_planner import AgentPlanner, ReplanningAgent, snapshot_cost
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


def make_env(world, tmp_path, **cfg):
    config = {"run_id": "r7w4", "seed": 1, "log_path": str(tmp_path / "log.jsonl")}
    config.update(cfg)
    return DeliverySimEnvironment(world, config)


def rows(env, name=None):
    with open(env.log_path, encoding="utf-8") as f:
        out = [json.loads(line) for line in f]
    return [r for r in out if name is None or r["event"] == name]


def close_road_at(env, u, v, after_s, duration_s=3600.0):
    def proc():
        yield env.env.timeout(after_s)
        t = env.get_current_time()
        env.world.add_disruption(u, v, 0, t + duration_s, start_t_seconds=t)
        env.handle_event(Event(t, "disruption", {
            "type": "closure", "edge": [u, v, 0], "magnitude": None,
            "duration": duration_s, "expiry": t + duration_s}))
    env.env.process(proc())


def counting_hook(calls):
    def hook(vid, route, routes, t):
        calls.append((vid, list(route.nodes), sorted(routes), t))
        return 3            # pretend: request, response, result
    return hook


# ---------------------------------------------------------------------------
# ReplanningAgent.on_world_change (unit level, no SimPy)
# ---------------------------------------------------------------------------
def test_on_world_change_reroutes_around_closure_on_path():
    world = FakeWorld(grid_graph())
    veh = Vehicle("V1", 0, 10.0, current_node=0)
    agent = ReplanningAgent(veh, world, [2], START)
    assert agent.planned == [0, 1, 2]
    world.add_disruption(1, 2, 0, START + 999, start_t_seconds=START)
    route = agent.on_world_change([(1, 2)], START)
    assert route.nodes[0] == 0 and route.nodes[-1] == 2
    assert (1, 2) not in list(zip(route.nodes, route.nodes[1:]))
    assert route.expected_times[-1] == START + 40.0
    assert veh.remaining_route == route.nodes[1:]


def test_on_world_change_accepts_events_payloads_and_tuples():
    for change in (
        Event(START, "disruption", {"type": "closure", "edge": [1, 2, 0]}),
        {"type": "closure", "edge": [1, 2, 0]},
        (1, 2, 0),
    ):
        w = FakeWorld(grid_graph())
        agent = ReplanningAgent(Vehicle("V", 0, 1.0, current_node=0), w, [2], START)
        w.add_disruption(1, 2, 0, START + 999, start_t_seconds=START)
        route = agent.on_world_change([change], START)
        assert route is not None and 2 not in route.nodes[1:2]


def test_closure_known_at_start_is_planned_around():
    w = FakeWorld(grid_graph())
    w.add_disruption(1, 2, 0, START + 999, start_t_seconds=START)
    agent = ReplanningAgent(Vehicle("V", 0, 1.0, current_node=0), w, [2], START)
    assert (1, 2) not in list(zip(agent.planned, agent.planned[1:]))
    assert agent.on_world_change([(1, 2)], START) is None     # nothing new


def test_no_change_seen_means_no_new_route():
    world = FakeWorld(grid_graph())
    agent = ReplanningAgent(Vehicle("V", 0, 1.0, current_node=0), world, [2], START)
    assert agent.on_world_change([(6, 7)], START) is None     # nothing changed
    assert agent.n_replans == 0


def test_mid_road_vehicle_replans_from_end_of_road():
    world = FakeWorld(grid_graph())
    veh = Vehicle("V1", 0, 10.0, current_node=0)
    agent = ReplanningAgent(veh, world, [2], START)
    veh.remaining_route.pop(0)                 # env popped 1 ...
    veh.current_edge = (0, 1, 0)               # ... and is driving 0 -> 1
    world.add_disruption(1, 2, 0, START + 999, start_t_seconds=START)
    route = agent.on_world_change([(1, 2)], START + 5)
    assert route.nodes[0] == 1                 # cannot turn back on 0 -> 1
    assert veh.remaining_route == route.nodes[1:]


def test_unreachable_stop_returns_empty_route_and_keeps_old_one():
    world = FakeWorld(grid_graph())
    veh = Vehicle("V1", 0, 10.0, current_node=0)
    agent = ReplanningAgent(veh, world, [2], START)
    old = list(veh.remaining_route)
    for u in (1, 5):
        world.add_disruption(u, 2, 0, START + 999, start_t_seconds=START)
    route = agent.on_world_change([(1, 2), (5, 2)], START)
    assert route.nodes == []
    assert agent.unreachable_stops == [2]
    assert veh.remaining_route == old          # W5 decides what to do


# ---------------------------------------------------------------------------
# Modes and the trigger_enabled toggle
# ---------------------------------------------------------------------------
def test_mode_rules(tmp_path):
    env = make_env(FakeWorld(grid_graph()), tmp_path)
    with pytest.raises(ValueError):
        AgentPlanner(env, mode="centralized")
    with pytest.raises(ValueError):
        AgentPlanner(env, mode="nonsense")
    with pytest.raises(ValueError):
        AgentPlanner(env, mode="independent", trigger_enabled=True)
    ind = AgentPlanner(env, mode="independent")
    assert ind.trigger_enabled is False
    with pytest.raises(ValueError):
        ind.set_trigger_enabled(True)
    assert AgentPlanner(env, mode="full", coordination=lambda *a: 0).trigger_enabled is True


def run_scenario(tmp_path, mode, hook=None, toggle_off_at=None, closures=((1, 2, 5),)):
    world = FakeWorld(grid_graph())
    env = make_env(world, tmp_path, mode=mode)
    planner = AgentPlanner(env, mode=mode, coordination=hook)
    v1 = Vehicle("V1", 0, 10.0, current_node=0)
    v2 = Vehicle("V2", 6, 10.0, current_node=6)
    o1, o2 = Order("o1", 2, 1.0, service_time=0.0), Order("o2", 8, 1.0, service_time=0.0)
    planner.register(v1, [o1])
    planner.register(v2, [o2])
    env.add_vehicle(v1, [o1])
    env.add_vehicle(v2, [o2])
    for u, v, at in closures:
        close_road_at(env, u, v, after_s=at)
    if toggle_off_at is not None:
        def off():
            yield env.env.timeout(toggle_off_at)
            planner.set_trigger_enabled(False)
        env.env.process(off())
    env.run(2000)
    summary = planner.finish()
    return env, planner, summary


def test_independent_mode_reroutes_and_sends_zero_negotiation_messages(tmp_path):
    calls = []
    env, planner, summary = run_scenario(tmp_path, "independent", hook=counting_hook(calls))
    assert calls == []                                   # hook never called
    assert summary["negotiation_messages"] == 0
    assert summary["negotiation_calls"] == 0
    assert summary["replans"] >= 1
    assert not rows(env, "blocked_wait")
    assert {r["payload"]["order_id"] for r in rows(env, "order_delivered")} == {"o1", "o2"}
    last = rows(env, "replan_summary")[-1]["payload"]
    assert last["negotiation_messages"] == 0 and last["mode"] == "independent"


def test_every_replan_logs_cpu_time(tmp_path):
    env, _, summary = run_scenario(
        tmp_path, "independent", closures=((1, 2, 5), (4, 5, 6), (7, 8, 12)))
    replans = rows(env, "replan")
    assert len(replans) == summary["replans"] >= 3
    for r in replans:
        assert r["payload"]["cpu_seconds"] >= 0
        assert r["payload"]["mode"] == "independent"
        assert "expanded" in r["payload"]


def test_full_mode_calls_coordination_after_each_replan(tmp_path):
    calls = []
    env, planner, summary = run_scenario(tmp_path, "full", hook=counting_hook(calls))
    assert len(calls) == summary["negotiation_calls"] == summary["replans"] >= 1
    vid, nodes, fleet, t = calls[0]
    assert fleet == ["V1", "V2"]                         # sees every vehicle's route
    assert summary["negotiation_messages"] == 3 * len(calls)


def test_trigger_toggle_at_run_time_stops_coordination(tmp_path):
    calls = []
    env, planner, summary = run_scenario(
        tmp_path, "full", hook=counting_hook(calls), toggle_off_at=8,
        closures=((1, 2, 5), (7, 8, 12)))
    toggles = rows(env, "trigger_toggle")
    assert toggles and toggles[0]["payload"]["trigger_enabled"] is False
    assert summary["replans"] >= 2
    assert len(calls) < summary["replans"]               # later replans not coordinated
    assert all(t < toggles[0]["t"] for *_, t in calls)


def test_no_path_is_handled_without_crashing(tmp_path):
    env, planner, summary = run_scenario(
        tmp_path, "independent", closures=((1, 2, 5), (5, 2, 5)))
    replans = [r for r in rows(env, "replan") if r["agent_id"] == "V1"]
    assert any(not r["payload"]["route_found"] for r in replans)
    assert summary["unreachable_stops"].get("V1") == [2]
    assert rows(env, "sim_complete")                     # the run finished


def test_register_uses_order_nodes_and_planner_interface(tmp_path):
    world = FakeWorld(grid_graph())
    env = make_env(world, tmp_path)
    planner = AgentPlanner(env)
    veh = Vehicle("V1", 0, 10.0, current_node=0, remaining_route=[1, 2, 5, 8])
    o = [Order("a", 5, 1.0), Order("b", 2, 1.0)]
    routes = planner.plan([veh], o)
    route = routes["V1"]
    assert route.nodes[0] == 0 and route.nodes[-1] == 8
    assert route.order_ids[route.nodes.index(2)] == "b"
    assert route.order_ids[route.nodes.index(5)] == "a"
    assert route.nodes.index(2) < route.nodes.index(5)   # route order kept


# ---------------------------------------------------------------------------
# R1's real disruption generator on the real (small) map
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(4))
def test_real_map_with_generated_disruptions_matches_astar(tmp_path, seed):
    """R1's EventGenerator closes and slows roads at 30 per hour; after every
    replan each agent's route cost equals a fresh A* on the D10 costs."""
    from src.search.heuristics import make_heuristic
    from src.world.graph_loader import load_road_graph
    G = load_road_graph("secunderabad_small")
    world = FakeWorld(G)
    env = make_env(world, tmp_path, seed=seed, mode="independent",
                   disruption_rate_per_hour=30.0)
    planner = AgentPlanner(env, heuristic=make_heuristic(G))
    rnd = random.Random(seed)
    nodes = sorted(G.nodes)
    for i in range(3):
        while True:
            start, a, b = rnd.sample(nodes, 3)
            if all(astar(G, x, y).cost < math.inf for x, y in ((start, a), (a, b))):
                break
        veh = Vehicle(f"V{i}", start, 10.0, current_node=start)
        orders = [Order(f"o{i}a", a, 1.0, service_time=0.0),
                  Order(f"o{i}b", b, 1.0, service_time=0.0)]
        planner.register(veh, orders, stops=[a, b])
        env.add_vehicle(veh, orders)

    checks = []

    def check(event):
        if event.event_type != "disruption":
            return
        cost_fn = snapshot_cost(world, event.t)
        for agent in planner.agents.values():
            p = agent.replanner.planner
            if p.done:
                continue
            ref, at = 0.0, p.position
            for s in p.remaining_stops:
                ref += astar(G, at, s, cost_fn, heuristic=lambda x, y: 0.0).cost
                at = s
            got = p.path_cost()
            checks.append(got == ref or math.isclose(got, ref, rel_tol=1e-9))
    env.subscribe(check)
    env.run(3600)
    summary = planner.finish()
    assert checks and all(checks)
    assert summary["negotiation_messages"] == 0
    assert len(rows(env, "replan")) == summary["replans"]
