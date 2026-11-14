"""Tests for Week 5 of src/sim/agent_planner.py and src/sim/coordination_hook.py
(R7): hysteresis, unreachable stops, and R5's trigger after every local replan
with no double replans.

Grid world 3 x 3 (node = 3 * row + col), every road 100 m at 10 m/s = 10 s.
"""
import json
import math
import random
from collections import Counter

import networkx as nx
import pytest

from src.coordination.trigger import NeverTrigger, ThresholdTrigger
from src.search.astar import astar
from src.sim.agent_planner import AgentPlanner, ReplanningAgent
from src.sim.coordination_hook import TriggerCoordination, to_vehicle_route
from src.sim.environment import DeliverySimEnvironment
from src.sim.interfaces import Route
from src.sim.models import Event, Order, Vehicle
from src.sim.world import FakeWorld

START = 21600.0
FAR = START + 99999


def grid_graph(n=3):
    G = nx.MultiDiGraph()
    for r in range(n):
        for c in range(n):
            a = n * r + c
            for b in ([a + 1] if c + 1 < n else []) + ([a + n] if r + 1 < n else []):
                G.add_edge(a, b, key=0, length=100.0)
                G.add_edge(b, a, key=0, length=100.0)
    return G


def graph_from(edges):
    """edges = [(u, v, metres)], both directions."""
    G = nx.MultiDiGraph()
    for u, v, m in edges:
        G.add_edge(u, v, key=0, length=float(m))
        G.add_edge(v, u, key=0, length=float(m))
    return G


def make_env(world, tmp_path, **cfg):
    config = {"run_id": "r7w5", "seed": 1, "log_path": str(tmp_path / "log.jsonl")}
    config.update(cfg)
    return DeliverySimEnvironment(world, config)


def rows(env, name=None):
    with open(env.log_path, encoding="utf-8") as f:
        out = [json.loads(line) for line in f]
    return [r for r in out if name is None or r["event"] == name]


def disrupt_at(env, u, v, after_s, kind="closure", magnitude=None, duration_s=3600.0):
    def proc():
        yield env.env.timeout(after_s)
        t = env.get_current_time()
        if kind == "closure":
            env.world.add_disruption(u, v, 0, t + duration_s, start_t_seconds=t)
        else:
            env.world.add_spike(u, v, 0, magnitude, t + duration_s, start_t_seconds=t)
        env.handle_event(Event(t, "disruption", {
            "type": kind, "edge": [u, v, 0], "magnitude": magnitude,
            "duration": duration_s, "expiry": t + duration_s}))
    env.env.process(proc())


def edges_of(nodes):
    return set(zip(nodes, nodes[1:]))


# ---------------------------------------------------------------------------
# Hysteresis
# ---------------------------------------------------------------------------
def two_route_agent(**kw):
    """0 -> 8 on the grid: several 40 s routes; returns (world, vehicle, agent)."""
    world = FakeWorld(grid_graph())
    veh = Vehicle("V1", 0, 10.0, current_node=0)
    agent = ReplanningAgent(veh, world, [8], START, **kw)
    return world, veh, agent


def test_small_gain_keeps_route():
    world, veh, agent = two_route_agent()
    old = list(veh.remaining_route)
    u, v = agent.planned[1], agent.planned[2]
    world.add_spike(u, v, 0, 1.5, FAR, start_t_seconds=START)      # 10 s -> 15 s
    assert agent.on_world_change([(u, v)], START) is None
    assert agent.last_decision == "kept"
    assert agent.last_gain == pytest.approx(5.0)                   # 45 s vs 40 s
    assert veh.remaining_route == old and agent.n_replans == 0 and agent.n_kept == 1
    assert agent.route.nodes == agent.planned
    assert agent.route.expected_times[-1] == pytest.approx(START + 45.0)   # ETAs updated


def test_big_gain_switches():
    world, veh, agent = two_route_agent()
    u, v = agent.planned[1], agent.planned[2]
    world.add_spike(u, v, 0, 5.0, FAR, start_t_seconds=START)      # 10 s -> 50 s
    route = agent.on_world_change([(u, v)], START)
    assert route is not None and agent.last_decision == "switched"
    assert (u, v) not in edges_of(route.nodes)
    assert agent.last_gain == pytest.approx(40.0)
    assert veh.remaining_route == route.nodes[1:]


def test_zero_margin_is_week4_behaviour():
    world, veh, agent = two_route_agent(min_gain_s=0.0, min_gain_frac=0.0)
    u, v = agent.planned[1], agent.planned[2]
    world.add_spike(u, v, 0, 1.5, FAR, start_t_seconds=START)
    assert agent.on_world_change([(u, v)], START) is not None
    assert agent.last_decision == "switched"


def test_fraction_margin_counts_on_long_routes():
    # gain 5 s on a 45 s route: above 10 % only if min_gain_s is lower
    world, veh, agent = two_route_agent(min_gain_s=0.0, min_gain_frac=0.2)
    u, v = agent.planned[1], agent.planned[2]
    world.add_spike(u, v, 0, 1.5, FAR, start_t_seconds=START)
    assert agent.on_world_change([(u, v)], START) is None          # 5 < 0.2 x 45
    world2, veh2, agent2 = two_route_agent(min_gain_s=0.0, min_gain_frac=0.1)
    u2, v2 = agent2.planned[1], agent2.planned[2]
    world2.add_spike(u2, v2, 0, 1.5, FAR, start_t_seconds=START)
    assert agent2.on_world_change([(u2, v2)], START) is not None   # 5 >= 0.1 x 45


def test_blocked_route_always_switches_whatever_the_margin():
    world, veh, agent = two_route_agent(min_gain_s=1e9, min_gain_frac=10.0)
    u, v = agent.planned[1], agent.planned[2]
    world.add_disruption(u, v, 0, FAR, start_t_seconds=START)
    route = agent.on_world_change([(u, v)], START)
    assert route is not None and (u, v) not in edges_of(route.nodes)


def test_bad_margins_rejected():
    with pytest.raises(ValueError):
        two_route_agent(min_gain_s=-1.0)


def test_no_flip_flop_between_near_equal_routes():
    """Small spikes land on whichever route the vehicle is on. Without
    hysteresis it switches every time; with it, never."""
    def flips(**kw):
        world, veh, agent = two_route_agent(**kw)
        t = START
        for i in range(12):
            u, v = agent.planned[1], agent.planned[2]
            world.add_spike(u, v, 0, 1.2, t + 5, start_t_seconds=t)
            agent.on_world_change([(u, v)], t)
            t += 5                                   # spike expires, roads re-checked
        return agent.n_replans
    assert flips(min_gain_s=0.0, min_gain_frac=0.0) >= 6
    assert flips() == 0


def test_same_path_after_change_is_not_a_replan():
    world, veh, agent = two_route_agent()
    world.add_spike(6, 7, 0, 3.0, FAR, start_t_seconds=START)       # cost moves elsewhere
    route = agent.on_world_change([(6, 7)], START)
    assert route is None and agent.n_replans == 0
    assert agent.last_decision in (None, "same")


# ---------------------------------------------------------------------------
# Unreachable stops
# ---------------------------------------------------------------------------
def cut_off_scenario(tmp_path, **planner_kw):
    """V1: stops 2 then 6; 2 is cut off at t = 5 while V1 drives 0 -> 1."""
    world = FakeWorld(grid_graph())
    env = make_env(world, tmp_path)
    planner = AgentPlanner(env, **planner_kw)
    veh = Vehicle("V1", 0, 10.0, current_node=0)
    o1 = Order("o1", 2, 1.0, service_time=0.0)
    o2 = Order("o2", 6, 1.0, service_time=0.0)
    planner.register(veh, [o1, o2], stops=[2, 6])
    env.add_vehicle(veh, [o1, o2])
    disrupt_at(env, 1, 2, 5)
    disrupt_at(env, 5, 2, 5)
    env.run(2000)
    return env, planner, planner.finish()


def test_unreachable_order_failed_and_rest_delivered(tmp_path):
    env, planner, summary = cut_off_scenario(tmp_path)
    failed = rows(env, "order_failed")
    assert [(r["payload"]["order_id"], r["payload"]["reason"]) for r in failed] == [
        ("o1", "unreachable")]
    assert [r["payload"]["order_id"] for r in rows(env, "order_delivered")] == ["o2"]
    assert not rows(env, "blocked_wait")                  # never waited at the closure
    su = rows(env, "stop_unreachable")
    assert len(su) == 1 and su[0]["payload"]["stops"] == [2]
    assert su[0]["payload"]["failed"] == ["o1"]
    assert summary["failed_unreachable"] == ["o1"]
    reasons = [r["payload"]["trigger"] for r in rows(env, "replan")]
    assert "unreachable" in reasons
    assert env.n_failed == 1                              # counted once, not again at route end


def test_reassign_hook_takes_the_order(tmp_path):
    asked = []

    def reassign(vid, orders, t):
        asked.append((vid, [o.id for o in orders], t))
        return orders                                     # R4 accepts all

    env, planner, summary = cut_off_scenario(tmp_path, reassign=reassign)
    assert asked and asked[0][0] == "V1" and asked[0][1] == ["o1"]
    assert summary["reassigned"] == ["o1"] and summary["failed_unreachable"] == []
    assert not rows(env, "order_failed")
    assert rows(env, "stop_unreachable")[0]["payload"]["reassigned"] == ["o1"]


def test_wait_policy_keeps_week4_behaviour(tmp_path):
    env, planner, summary = cut_off_scenario(tmp_path, unreachable="wait")
    assert summary["failed_unreachable"] == []
    assert summary["unreachable_stops"] == {"V1": [2]}
    assert not rows(env, "stop_unreachable")
    with pytest.raises(ValueError):
        AgentPlanner(make_env(FakeWorld(grid_graph()), tmp_path), unreachable="maybe")


def test_dropping_a_stop_can_cut_off_the_next_one():
    # line 0 - 1 - 2 - 3; closing 1 -> 2 cuts off 2, and 3 can only be reached via 2
    world = FakeWorld(graph_from([(0, 1, 100), (1, 2, 100), (2, 3, 100)]))
    veh = Vehicle("V1", 0, 10.0, current_node=0)
    agent = ReplanningAgent(veh, world, [2, 3], START)
    world.add_disruption(1, 2, 0, FAR, start_t_seconds=START)
    route = agent.on_world_change([(1, 2)], START)
    assert route.nodes == [] and agent.unreachable_stops == [2]    # leg 2 -> 3 is fine
    route = agent.drop_stops(agent.unreachable_stops, START)
    assert agent.dropped == [2, 3]
    assert route.nodes == [0] and veh.remaining_route == []
    assert agent.replanner.planner.done


# ---------------------------------------------------------------------------
# R5's trigger after every local replan
# ---------------------------------------------------------------------------
def conflict_world():
    """V1 0 -> 1 -> 2 and V2 4 -> 1 -> 2 both use road 1 -> 2 in [10, 20] s.
    A side road 1 -> 3 -> 2 costs 2 s more (detour 2 s < wait 10 s)."""
    return FakeWorld(graph_from([(0, 1, 100), (4, 1, 100), (1, 2, 100),
                                 (1, 3, 60), (3, 2, 60)]))


def two_vehicle_full(tmp_path, trigger, priority_v1=3, **hook_kw):
    world = conflict_world()
    env = make_env(world, tmp_path, mode="full")
    hook = TriggerCoordination(trigger, **hook_kw)
    planner = AgentPlanner(env, mode="full", coordination=hook)
    v1 = Vehicle("V1", 0, 10.0, current_node=0)
    v2 = Vehicle("V2", 4, 10.0, current_node=4)
    o1 = Order("o1", 2, 1.0, priority=priority_v1, service_time=0.0)
    o2 = Order("o2", 2, 1.0, priority=1, service_time=0.0)
    planner.register(v1, [o1], stops=[2])
    planner.register(v2, [o2], stops=[2])
    env.add_vehicle(v1, [o1])
    env.add_vehicle(v2, [o2])
    return env, planner, hook


def test_to_vehicle_route_drops_the_part_already_driven():
    r = Route([0, 1, 2, 2, 5], [100.0, 110.0, 120.0, 120.0, 130.0], [None] * 5)
    vr = to_vehicle_route("V", r, 115.0, priority_weight=2.0)
    assert list(vr.nodes) == [1, 2, 5] and vr.start_time == 110.0
    assert vr.travel_times == {(1, 2): 10.0, (2, 5): 10.0}
    assert vr.priority_weight == 2.0
    assert to_vehicle_route("V", Route([7], [1.0], [None]), 0.0) is None


def test_trigger_fires_auction_runs_loser_detours(tmp_path):
    env, planner, hook = two_vehicle_full(tmp_path, ThresholdTrigger(tau=300.0))
    assert edges_of(planner.agents["V2"].planned) >= {(4, 1), (1, 2)}
    planner._after_replan("V1", planner.agents["V1"].route, START)
    # R5's auction: 3 messages per vehicle (D7)
    assert planner.negotiation_messages == 6 == hook.counter.total_messages
    assert hook.auctions == 1
    result = rows(env, "negotiation_result")[-1]["payload"]
    assert result["winner"] == "V1" and result["vehicles"] == ["V1", "V2"]
    assert result["actions"] == {"V2": "detour"}
    assert result["price"] == pytest.approx(2.0)          # V2's bid: 1 x 2 s detour
    assert hook.budgets["V1"].credits == pytest.approx(98.0)
    assert len(rows(env, "negotiation_request")) == 2
    assert len(rows(env, "negotiation_response")) == 2
    # V2 detoured once, logged as a replan; the hook was not called again
    assert planner.agents["V2"].planned == [4, 1, 3, 2]
    yields = rows(env, "replan")
    assert [(r["agent_id"], r["payload"]["trigger"]) for r in yields] == [
        ("V2", "negotiation_yield")]
    assert planner.negotiation_calls == 1 and planner.yields == 1
    env.run(500)
    entered = {(r["agent_id"], tuple(r["payload"]["edge"][:2])) for r in rows(env, "edge_enter")}
    assert ("V1", (1, 2)) in entered and ("V2", (1, 2)) not in entered
    assert len(rows(env, "order_delivered")) == 2


def test_loser_waits_when_detour_costs_more(tmp_path):
    # V1 low priority loses (tie on bids -> lowest id V1 wins, so give V2 more
    # priority); V1's detour 2 s is cheap: it detours. Make the side road long
    # instead so waiting is cheaper.
    world = FakeWorld(graph_from([(0, 1, 100), (4, 1, 100), (1, 2, 100),
                                  (1, 3, 600), (3, 2, 600)]))
    env = make_env(world, tmp_path, mode="full")
    hook = TriggerCoordination(ThresholdTrigger(tau=300.0))
    planner = AgentPlanner(env, mode="full", coordination=hook)
    for vid, node, prio in (("V1", 0, 3), ("V2", 4, 1)):
        veh = Vehicle(vid, node, 10.0, current_node=node)
        planner.register(veh, [Order("o" + vid, 2, 1.0, priority=prio)], stops=[2])
    before = list(planner.agents["V2"].planned)
    planner._after_replan("V1", planner.agents["V1"].route, START)
    assert rows(env, "negotiation_result")[-1]["payload"]["actions"] == {"V2": "wait"}
    assert planner.agents["V2"].planned == before and planner.yields == 0


def test_never_trigger_finds_conflict_but_sends_nothing(tmp_path):
    env, planner, hook = two_vehicle_full(tmp_path, NeverTrigger())
    planner._after_replan("V1", planner.agents["V1"].route, START)
    assert planner.negotiation_messages == 0 and hook.auctions == 0
    assert hook.not_triggered == 1
    assert not rows(env, "negotiation_result")


def test_threshold_tau_below_ttc_does_not_fire(tmp_path):
    env, planner, hook = two_vehicle_full(tmp_path, ThresholdTrigger(tau=5.0))
    planner._after_replan("V1", planner.agents["V1"].route, START)   # TTC = 10 s
    assert hook.auctions == 0 and hook.not_triggered == 1


def test_same_conflict_is_rate_limited(tmp_path):
    env, planner, hook = two_vehicle_full(
        tmp_path, ThresholdTrigger(tau=300.0), priority_v1=1, rate_limit_s=5.0)
    world = planner.env.world
    # make detours impossible so nobody moves and the conflict stays
    world.add_disruption(1, 3, 0, FAR, start_t_seconds=START)
    for a in planner.agents.values():
        a.replanner.watched.add((1, 3))
        a.replanner.refresh(START)
    planner._after_replan("V1", planner.agents["V1"].route, START)
    planner._after_replan("V2", planner.agents["V2"].route, START + 1)
    assert hook.auctions == 1 and hook.rate_limited == 1
    planner._after_replan("V2", planner.agents["V2"].route, START + 6)   # window over
    assert hook.auctions == 2


def test_independent_mode_never_calls_the_hook(tmp_path):
    world = conflict_world()
    env = make_env(world, tmp_path)
    hook = TriggerCoordination(ThresholdTrigger(tau=300.0))
    planner = AgentPlanner(env, mode="independent", coordination=hook)
    for vid, node in (("V1", 0), ("V2", 4)):
        veh = Vehicle(vid, node, 10.0, current_node=node)
        o = Order("o" + vid, 2, 1.0, service_time=0.0)
        planner.register(veh, [o], stops=[2])
        env.add_vehicle(veh, [o])
    disrupt_at(env, 1, 2, 3)
    env.run(500)
    s = planner.finish()
    assert s["replans"] >= 2 and s["negotiation_messages"] == 0 and hook.auctions == 0
    assert not rows(env, "negotiation_request")


def real_map_full_run(tmp_path, seed, rate=600.0, n_vehicles=8, n_stops=4):
    """R1's generator on the small real map, full mode with R5's
    ThresholdTrigger; every vehicle ends at one shared hub (real conflicts)."""
    from src.search.heuristics import make_heuristic
    from src.world.graph_loader import load_road_graph
    G = load_road_graph("secunderabad_small")
    world = FakeWorld(G)
    env = make_env(world, tmp_path, seed=seed, mode="full",
                   disruption_rate_per_hour=rate)
    calls = []

    class Spy(TriggerCoordination):
        def __call__(self, vid, route, routes, t):
            calls.append((vid, t))
            return super().__call__(vid, route, routes, t)

    hook = Spy(ThresholdTrigger(tau=600.0), rate_limit_s=60.0)
    planner = AgentPlanner(env, mode="full", heuristic=make_heuristic(G), coordination=hook)
    rnd = random.Random(seed)
    nodes = sorted(G.nodes)
    hub = rnd.choice(nodes)
    for i in range(n_vehicles):
        while True:
            pick = rnd.sample(nodes, n_stops)
            start, stops = pick[0], pick[1:] + [hub]
            legs = list(zip([start] + stops, stops))
            if all(astar(G, x, y).cost < math.inf for x, y in legs):
                break
        veh = Vehicle(f"V{i}", start, 10.0, current_node=start)
        orders = [Order(f"o{i}_{j}", n, 1.0, service_time=0.0) for j, n in enumerate(stops)]
        planner.register(veh, orders, stops=stops)
        env.add_vehicle(veh, orders)
    env.run(3600)
    return env, planner, planner.finish(), calls, hook


@pytest.mark.parametrize("seed", range(3))
def test_full_mode_on_real_map_no_double_replans(tmp_path, seed):
    """The hook runs exactly once per local replan that found a route; a
    negotiation detour never calls it; each vehicle replans at most once per
    disruption; message counts add up."""
    env, planner, s, calls, hook = real_map_full_run(tmp_path, seed)
    replans = rows(env, "replan")
    local = [r for r in replans
             if r["payload"]["trigger"] != "negotiation_yield" and r["payload"]["route_found"]]
    assert len(local) >= 3                                # not a vacuous run
    assert len(calls) == len(local) == s["negotiation_calls"]
    per_event = Counter((r["agent_id"], r["t"]) for r in replans
                        if r["payload"]["trigger"] in ("closure", "traffic_spike"))
    assert all(n == 1 for n in per_event.values())
    results = rows(env, "negotiation_result")
    assert s["negotiation_messages"] == 3 * sum(r["payload"]["count"] for r in results)
    assert len(rows(env, "negotiation_request")) == sum(r["payload"]["count"] for r in results)
    assert s["yields"] == len([r for r in replans
                               if r["payload"]["trigger"] == "negotiation_yield"])
    assert rows(env, "sim_complete")


def test_real_map_runs_do_negotiate(tmp_path):
    """Across the seeds above, the trigger fired and some loser detoured."""
    auctions = yields = 0
    for seed in range(3):
        env, planner, s, calls, hook = real_map_full_run(tmp_path / str(seed), seed)
        auctions += hook.auctions
        yields += s["yields"]
    assert auctions >= 1 and yields >= 1
