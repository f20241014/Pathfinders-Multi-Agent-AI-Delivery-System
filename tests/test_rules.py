"""Each rule has a positive (passes) and a negative (blocks) case.  Run: pytest -q"""
import math

from src.kr.ontology import ALL_ROAD_CLASSES, NARROW_ROAD_CLASSES, Order, Vehicle, Zone
from src.kr.rules import feasible, road_allowed, violated_rules

# Line world: nodes 0..10, 60 s per unit of distance. Depot at 0.
def tt(a, b, t):
    return 60.0 * abs(a - b)

def unreachable_tt(a, b, t):
    return math.inf if b == 7 else 60.0 * abs(a - b)

def veh(**kw):
    base = dict(id="V1", depot_node=0, capacity=10, shift_end=4 * 3600)
    base.update(kw)
    return Vehicle(**base)

def order(i, node, **kw):
    base = dict(id=i, node=node, demand=1, priority=2, service_time=60)
    base.update(kw)
    return Order(**base)


# R01 capacity
def test_R01_ok():
    ok, tr = feasible(veh(), [order("A", 2, demand=4), order("B", 3, demand=6)], tt)
    assert ok and any("ok load 10/10" in l for l in tr)

def test_R01_fail_counts_existing_load():
    ok, tr = feasible(veh(load=5), [order("A", 2, demand=6)], tt)
    assert not ok and violated_rules(tr) == ["R01"]


# R11 release time
def test_R11_ok():
    assert feasible(veh(), [order("A", 2, release_time=100)], tt, t_now=100)[0]

def test_R11_fail():
    ok, tr = feasible(veh(), [order("A", 2, release_time=500)], tt, t_now=100)
    assert not ok and violated_rules(tr) == ["R11"]


# R07 wait for tw_start, R09 departure = start + service
def test_R07_waits_instead_of_failing():
    ok, tr = feasible(veh(), [order("A", 1, tw_start=600, tw_end=900)], tt)
    assert ok and any("A waits 540s" in l for l in tr)

def test_R09_service_time_pushes_next_stop_late():
    # A at node 1 arrives 60, service 1000 -> leaves 1060; B at node 2 arrives 1120 > tw_end 1100
    os_ = [order("A", 1, service_time=1000, priority=1), order("B", 2, tw_start=0, tw_end=1100, priority=2)]
    ok, tr = feasible(veh(), os_, tt)
    assert ok  # feasible only because the override reorders B first
    assert any("R13 overridden by R08" in l for l in tr)


# R08 time-window end
def test_R08_ok():
    assert feasible(veh(), [order("A", 5, tw_start=0, tw_end=400)], tt)[0]

def test_R08_fail():
    ok, tr = feasible(veh(), [order("A", 5, tw_start=0, tw_end=200)], tt)   # arrives 300
    assert not ok and "R08" in violated_rules(tr)


# R10 shift end
def test_R10_ok():
    assert feasible(veh(shift_end=1000), [order("A", 5)], tt)[0]   # 300 + 60 + 300 = 660

def test_R10_fail():
    ok, tr = feasible(veh(shift_end=600), [order("A", 5)], tt)
    assert not ok and violated_rules(tr) == ["R10"]


# R13 priority ordering (soft) and its override
def test_R13_express_first_when_possible():
    ok, tr = feasible(veh(), [order("S", 1, priority=3), order("E", 8, priority=1)], tt)
    assert ok and tr[-1] == "FEASIBLE: E -> S"

def test_R13_overridden_when_it_breaks_a_window():
    os_ = [order("E", 9, priority=1), order("S", 1, priority=3, tw_start=0, tw_end=200)]
    ok, tr = feasible(veh(), os_, tt)
    assert ok and tr[-1] == "FEASIBLE: S -> E"

def test_R13_override_still_infeasible_reports_R08():
    os_ = [order("E", 9, priority=1, tw_start=0, tw_end=100), order("S", 8, priority=3, tw_start=0, tw_end=100)]
    ok, tr = feasible(veh(), os_, tt)
    assert not ok and "R08" in violated_rules(tr)


# unreachable destination (road rules leave no path)
def test_unreachable():
    ok, tr = feasible(veh(), [order("A", 7)], unreachable_tt)
    assert not ok and violated_rules(tr) == ["REACH"]


def test_empty_set_is_feasible():
    assert feasible(veh(), [], tt)[0]


# road_allowed: R04 closure, R03 road class, R06 zone
large = veh(id="L1", vehicle_class="large", allowed_road_classes=ALL_ROAD_CLASSES - NARROW_ROAD_CLASSES)

def test_R04():
    assert road_allowed(veh(), 1, 2, {"highway": "primary"}, 0)[0]
    ok, why = road_allowed(veh(), 1, 2, {"highway": "primary"}, 0, is_blocked=lambda u, v, t: (u, v) == (1, 2))
    assert not ok and why.startswith("R04")

def test_R03():
    assert road_allowed(large, 1, 2, {"highway": "secondary"}, 0)[0]
    ok, why = road_allowed(large, 1, 2, {"highway": "residential"}, 0)
    assert not ok and why.startswith("R03")
    assert road_allowed(veh(), 1, 2, {"highway": "residential"}, 0)[0]   # small vehicle is fine

def test_R03_osmnx_list_uses_most_restrictive():
    assert not road_allowed(large, 1, 2, {"highway": ["primary", "residential"]}, 0)[0]

def test_R06():
    z = Zone("old_city", frozenset({2}), start=0, end=3600)
    assert not road_allowed(large, 1, 2, {"highway": "primary"}, 100, zones=[z])[0]
    assert road_allowed(large, 1, 2, {"highway": "primary"}, 4000, zones=[z])[0]   # after hours
    assert road_allowed(veh(), 1, 2, {"highway": "primary"}, 100, zones=[z])[0]    # small vehicle

