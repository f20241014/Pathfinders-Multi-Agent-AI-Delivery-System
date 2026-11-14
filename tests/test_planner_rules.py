"""R3 Week 4: rules inside the planners (blocked edges, priority ordering, trace in the log).

Grid 3 x 3 (node = 3 * row + col), every road 100 m at 10 m/s = 10 s. The top row 0-1-2 is
residential; everything else is primary. A large vehicle (no narrow roads) must go round it.
"""

import json

import networkx as nx
import pytest

from src.allocation.world_adapter import WorldTravel
from src.kr.ontology import SIM_START_S as T, Order, Vehicle, Zone
from src.kr.planner_rules import (
    LARGE_VEHICLE_CLASSES,
    RoadRules,
    log_kr_trace,
    priority_stops,
    zones_from_config,
)
from src.search.astar import astar
from src.search.dijkstra import free_flow_cost
from src.sim.agent_planner import AgentPlanner, ReplanningAgent
from src.sim.environment import DeliverySimEnvironment
from src.sim.logger import SimulationLogger
from src.sim.models import Order as SimOrder
from src.sim.models import Vehicle as SimVehicle
from src.sim.world import FakeWorld

RESIDENTIAL_ROW = {(0, 1), (1, 0), (1, 2), (2, 1)}


def grid(n=3):
    G = nx.MultiDiGraph()
    for r in range(n):
        for c in range(n):
            a = n * r + c
            for b in ([a + 1] if c + 1 < n else []) + ([a + n] if r + 1 < n else []):
                cls = "residential" if (a, b) in RESIDENTIAL_ROW else "primary"
                for x, y in ((a, b), (b, a)):
                    G.add_edge(x, y, key=0, length=100.0, highway=cls, free_flow_time=10.0)
    return G


def large(vid="L", node=0):
    return SimVehicle(
        vid, node, 10.0, current_node=node, allowed_road_classes=LARGE_VEHICLE_CLASSES
    )


def small(vid="S", node=0):
    return SimVehicle(vid, node, 10.0, current_node=node)


def zero_h(node, goal):
    return 0.0  # admissible on a grid with no coordinates


def edges_of(path):
    return set(zip(path, path[1:]))


# ------------------------------------------------------------ blocked edges
def test_class_blocked_edges_for_large_vehicle_only():
    rules = RoadRules(grid())
    assert set(rules.class_blocked(large())) == RESIDENTIAL_ROW
    assert rules.class_blocked(small()) == {}
    assert rules.explain_edge(large(), 0, 1).startswith("KR-3")
    assert rules.explain_edge(small(), 0, 1) == "ok"


def test_parallel_road_of_an_allowed_class_keeps_the_pair_open():
    G = grid()
    G.add_edge(0, 1, key=1, length=150.0, highway="secondary", free_flow_time=15.0)
    blocked = RoadRules(G).class_blocked(large())
    assert (0, 1) not in blocked and (1, 0) in blocked


def test_zone_blocks_roads_into_it_only_during_its_hours():
    z = Zone("market", frozenset({4}), start=T, end=T + 3600)
    rules = RoadRules(grid(), zones=[z])
    during = rules.zone_blocked(large(), T + 10)
    assert set(during) == {(1, 4), (3, 4), (5, 4), (7, 4)}
    assert all(until == T + 3600 for _, until in during.values())
    assert rules.zone_blocked(large(), T + 4000) == {}
    assert rules.zone_blocked(small(), T + 10) == {}


def test_astar_with_rule_cost_fn_goes_round_residential_row():
    G = grid()
    rules = RoadRules(G)
    small_path = astar(G, 0, 2, rules.cost_fn(small(), free_flow_cost), zero_h).path
    large_path = astar(G, 0, 2, rules.cost_fn(large(), free_flow_cost), zero_h).path
    assert small_path == [0, 1, 2]
    assert large_path[0] == 0 and large_path[-1] == 2
    assert not edges_of(large_path) & RESIDENTIAL_ROW


def test_cost_fn_honours_closures():
    G = grid()
    rules = RoadRules(G, is_blocked=lambda u, v, t: (u, v) == (0, 1))
    path = astar(G, 0, 2, rules.cost_fn(small(), free_flow_cost), zero_h).path
    assert (0, 1) not in edges_of(path)
    assert rules.blocked_edges(small(), T) == {(0, 1): "KR-4 edge closed"}


# ------------------------------------------------------------ R1 world view, R7's agents, R4
def test_view_reports_forbidden_roads_as_blocked_and_delegates_the_rest():
    world = FakeWorld(grid())
    view = RoadRules(world.graph()).view(world, large())
    assert view.is_blocked(0, 1, T) and not world.is_blocked(0, 1, T)
    assert view.edge_time(0, 1, T) == float("inf") and view.edge_time(0, 3, T) == 10.0
    assert view.cost_fn_at(T)(0, 1) == float("inf")
    assert view.graph() is world.graph() and view.closures is world.closures
    world.add_disruption(0, 3, 0, T + 999, start_t_seconds=T)
    assert view.is_blocked(0, 3, T)  # real closures still count


def test_r7_agent_on_view_never_plans_a_forbidden_road():
    world = FakeWorld(grid())
    rules = RoadRules(world.graph())
    plain = ReplanningAgent(large("A"), world, [2], T)
    ruled = ReplanningAgent(large("B"), rules.view(world, large("B")), [2], T)
    assert plain.planned == [0, 1, 2]
    assert ruled.planned[-1] == 2 and not edges_of(ruled.planned) & RESIDENTIAL_ROW


def test_r7_agent_on_view_replans_round_a_closure_and_still_obeys_rules():
    world = FakeWorld(grid())
    veh = large("B")
    agent = ReplanningAgent(veh, RoadRules(world.graph()).view(world, veh), [2], T)
    assert agent.planned == [0, 3, 4, 5, 2]
    world.add_disruption(4, 5, 0, T + 999, start_t_seconds=T)
    route = agent.on_world_change([(4, 5)], T)
    assert route.nodes[0] == 0 and route.nodes[-1] == 2
    assert (4, 5) not in edges_of(route.nodes) and not edges_of(route.nodes) & RESIDENTIAL_ROW


def test_r4_world_travel_on_view_avoids_a_zone():
    world = FakeWorld(grid())
    rules = RoadRules(world.graph(), zones=[Zone("market", frozenset({4}), start=T, end=T + 3600)])
    veh = large()
    _, path = WorldTravel(rules.view(world, veh), T).path(veh, 3, 5)
    assert path[0] == 3 and path[-1] == 5 and 4 not in path
    _, open_path = WorldTravel(world, T).path(veh, 3, 5)
    assert open_path == [3, 4, 5]


# ------------------------------------------------------------ priority ordering
def line_tt(a, b, t):
    return 10.0 * abs(a - b)


def test_priority_stops_express_first_then_depot():
    v = Vehicle("V", 0, 10)
    orders = [Order("eco", 2, 1, 3, service_time=0), Order("exp", 8, 1, 1, service_time=0)]
    stops, result = priority_stops(v, orders, line_tt)
    assert stops == [8, 2, 0] and result["feasible"]


def test_priority_stops_follow_the_window_override():
    v = Vehicle("V", 0, 10)
    orders = [
        Order("exp", 8, 1, 1, service_time=0),
        Order("eco", 2, 1, 3, tw_start=T, tw_end=T + 30, service_time=0),
    ]
    stops, result = priority_stops(v, orders, line_tt)
    assert stops == [2, 8, 0] and result["feasible"]
    assert any("KR-13 overridden by KR-8" in line for line in result["trace"])


def test_priority_stops_still_return_a_route_when_infeasible():
    v = Vehicle("V", 0, 1)
    orders = [Order("a", 2, 1, 2, service_time=0), Order("b", 5, 1, 1, service_time=0)]
    stops, result = priority_stops(v, orders, line_tt)
    assert stops == [5, 2, 0] and not result["feasible"] and result["violated"] == ["KR-1"]


def test_priority_stops_merge_orders_at_the_same_node():
    v = Vehicle("V", 0, 10)
    orders = [Order("a", 4, 1, 2, service_time=0), Order("b", 4, 1, 1, service_time=0)]
    assert priority_stops(v, orders, line_tt, end_at_depot=False)[0] == [4]


def test_express_order_is_delivered_first_in_r1_sim(tmp_path):
    """End to end: rules order the stops, R7's planner drives them, R1's env delivers them."""
    world = FakeWorld(grid())
    env = DeliverySimEnvironment(
        world, {"run_id": "kr4", "seed": 1, "log_path": str(tmp_path / "log.jsonl")}
    )
    planner = AgentPlanner(env, mode="independent")
    veh = small("V1")
    # eco listed first; the route to exp (0-1-2) does not pass eco's node 6
    orders = [
        SimOrder("eco", 6, 1.0, priority=3, service_time=0.0),
        SimOrder("exp", 2, 1.0, priority=1, service_time=0.0),
    ]

    def travel(u, v, t):
        return nx.shortest_path_length(world.graph(), u, v, weight="free_flow_time")

    stops, result = priority_stops(veh, orders, travel, T)
    planner.register(veh, orders, stops=stops)
    env.add_vehicle(veh, orders)
    log_kr_trace(env, T, veh.id, result, context="register")
    env.run(2000)
    rows = [json.loads(line) for line in open(tmp_path / "log.jsonl")]
    delivered = [r["payload"]["order_id"] for r in rows if r["event"] == "order_delivered"]
    assert delivered == ["exp", "eco"]
    kr = [r for r in rows if r["event"] == "kr_check"]
    assert len(kr) == 1 and kr[0]["agent_id"] == "V1" and kr[0]["payload"]["feasible"]
    assert kr[0]["payload"]["sequence"] == ["exp", "eco"]


def test_without_priority_stops_the_listed_order_is_driven(tmp_path):
    """Contrast for the test above: R7's default stop order is the order list, eco first."""
    world = FakeWorld(grid())
    env = DeliverySimEnvironment(
        world, {"run_id": "kr4b", "seed": 1, "log_path": str(tmp_path / "log.jsonl")}
    )
    planner = AgentPlanner(env, mode="independent")
    veh = small("V1")
    orders = [
        SimOrder("eco", 6, 1.0, priority=3, service_time=0.0),
        SimOrder("exp", 2, 1.0, priority=1, service_time=0.0),
    ]
    planner.register(veh, orders)
    env.add_vehicle(veh, orders)
    env.run(2000)
    rows = [json.loads(line) for line in open(tmp_path / "log.jsonl")]
    assert [r["payload"]["order_id"] for r in rows if r["event"] == "order_delivered"] == [
        "eco",
        "exp",
    ]


# ------------------------------------------------------------ trace logging, configs
def test_log_kr_trace_with_r1_logger(tmp_path):
    logger = SimulationLogger(str(tmp_path / "l.jsonl"), "r", "independent", 0, "s", 0.0)
    result = {"feasible": False, "violated": ["KR-1"], "sequence": [], "trace": ["KR-1: FAIL"]}
    log_kr_trace(logger, T + 5, "V9", result, context="bid")
    row = json.loads(open(tmp_path / "l.jsonl").read())
    assert row["event"] == "kr_check" and row["agent_id"] == "V9" and row["t"] == T + 5
    assert row["payload"]["violated"] == ["KR-1"] and row["payload"]["context"] == "bid"


def test_zones_from_config():
    cfg = {"kr_zones": [{"id": "old_city", "nodes": [4, 5], "start": T, "end": T + 3600}]}
    (z,) = zones_from_config(cfg)
    assert z.nodes == frozenset({4, 5}) and z.restricts("large", T + 1)
    assert not z.restricts("small", T + 1) and zones_from_config({}) == []


@pytest.mark.parametrize("veh,expected", [(large(), "large"), (small(), "small")])
def test_vehicle_class_inferred_from_allowed_roads(veh, expected):
    from src.kr.ontology import class_of

    assert class_of(veh) == expected