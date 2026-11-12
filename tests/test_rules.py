"""Each rule has a passing and a blocking case; plus forward chaining, R1 models and R4's adapter.
Times are seconds since midnight; T is 06:00.  Run: python -m pytest tests/test_rules.py -q
"""

import math

from src.kr.engine import WorkingMemory
from src.kr.ontology import (
    ALL_ROAD_CLASSES,
    NARROW_ROAD_CLASSES,
    SIM_START_S as T,
    Order,
    Vehicle,
    Zone,
)
from src.kr.rules import _ENGINE, feasible, road_allowed, run_feasibility_engine, violated_rules


# Line world: nodes 0..10, 60 s per unit of distance. Depot at 0.
def tt(a, b, t):
    return 60.0 * abs(a - b)


def unreachable_tt(a, b, t):
    return math.inf if b == 7 else 60.0 * abs(a - b)


def veh(**kw):
    base = dict(id="V1", depot_node=0, capacity=10, shift_end=T + 4 * 3600)
    base.update(kw)
    return Vehicle(**base)


def order(i, node, tw=None, **kw):
    base = dict(
        id=i,
        node=node,
        demand=1,
        priority=2,
        service_time=60,
        release_time=T,
        tw_start=T + tw[0] if tw else None,
        tw_end=T + tw[1] if tw else None,
    )
    base.update(kw)
    return Order(**base)


# KR-1 capacity
def test_kr1_ok():
    ok, tr = feasible(veh(), [order("A", 2, demand=4), order("B", 3, demand=6)], tt)
    assert ok and any("ok load 10/10" in line for line in tr)


def test_kr1_fail_counts_vehicle_load():
    ok, tr = feasible(veh(load=5), [order("A", 2, demand=6)], tt)
    assert not ok and violated_rules(tr) == ["KR-1"]


# KR-11 release time
def test_kr11_ok():
    assert feasible(veh(), [order("A", 2, release_time=T + 100)], tt, t_now=T + 100)[0]


def test_kr11_fail():
    ok, tr = feasible(veh(), [order("A", 2, release_time=T + 500)], tt, t_now=T + 100)
    assert not ok and violated_rules(tr) == ["KR-11"]


# KR-7 wait for tw_start, KR-9 departure = start + service
def test_kr7_waits_instead_of_failing():
    ok, tr = feasible(veh(), [order("A", 1, tw=(600, 900))], tt)
    assert ok and any("A waits 540s" in line for line in tr)


def test_kr9_service_time_pushes_next_stop_late():
    os_ = [order("A", 1, service_time=1000, priority=1), order("B", 2, tw=(0, 1100), priority=2)]
    ok, tr = feasible(veh(), os_, tt)
    assert ok and any("KR-13 overridden by KR-8" in line for line in tr)


# KR-8 time-window end
def test_kr8_ok():
    assert feasible(veh(), [order("A", 5, tw=(0, 400))], tt)[0]


def test_kr8_fail():
    ok, tr = feasible(veh(), [order("A", 5, tw=(0, 200))], tt)  # arrives at T + 300
    assert not ok and "KR-8" in violated_rules(tr)


# KR-10 back at the depot by shift end; KR-10a shift duration
def test_kr10_ok():
    assert feasible(veh(shift_end=T + 1000), [order("A", 5)], tt)[0]  # 300 + 60 + 300 = 660


def test_kr10_fail():
    ok, tr = feasible(veh(shift_end=T + 600), [order("A", 5)], tt)
    assert not ok and violated_rules(tr) == ["KR-10"]


def test_kr10a_shift_duration_without_travel_times():
    os_ = [order("A", 1, service_time=2000), order("B", 2, service_time=2000)]
    assert run_feasibility_engine(veh(shift_end=T + 5000), os_)["feasible"]
    r = run_feasibility_engine(veh(shift_end=T + 3000), os_)
    assert not r["feasible"] and r["violated"] == ["KR-10a"]


# KR-13 priority ordering (soft) and its overrides
def test_kr13_express_first_when_possible():
    ok, tr = feasible(veh(), [order("S", 1, priority=3), order("E", 8, priority=1)], tt)
    assert ok and tr[-1] == "FEASIBLE: E -> S"


def test_kr13_overridden_when_it_breaks_a_window():
    ok, tr = feasible(
        veh(), [order("E", 9, priority=1), order("S", 1, priority=3, tw=(0, 200))], tt
    )
    assert ok and tr[-1] == "FEASIBLE: S -> E"


def test_kr13y_exact_search_when_priority_and_edf_both_fail():
    a = order("A", 10, tw=(0, 2000), priority=3)
    b = order("B", 1, tw=(1500, 1600), priority=1)
    ok, tr = feasible(veh(), [a, b], tt)
    assert ok and tr[-1] == "FEASIBLE: A -> B" and any(line.startswith("KR-13y") for line in tr)


def test_kr13_still_infeasible_reports_kr8():
    os_ = [order("E", 9, priority=1, tw=(0, 100)), order("S", 8, priority=3, tw=(0, 100))]
    ok, tr = feasible(veh(), os_, tt)
    assert not ok and "KR-8" in violated_rules(tr)


def test_unreachable():
    ok, tr = feasible(veh(), [order("A", 7)], unreachable_tt)
    assert not ok and violated_rules(tr) == ["REACH"]


def test_empty_set_is_feasible():
    assert feasible(veh(), [], tt)[0]


# forward chaining: later rules fire only on facts earlier rules derived
def test_rules_chain_through_derived_facts():
    wm = WorkingMemory()
    wm.assert_fact("ctx", t=T, check_release=True, travel_time=tt)
    wm.assert_fact("vehicle", vehicle=veh())
    wm.assert_fact("order", order=order("A", 2, demand=3))
    trace = _ENGINE.run(wm)
    assert wm.one("load_total")["total"] == 3
    for fact in ("capacity_ok", "release_ok", "shift_duration_ok", "sequence"):
        assert wm.facts(fact), fact
    names = [line.split(":")[0] for line in trace]
    assert names.index("LOAD") < names.index("KR-1") < names.index("KR-13") < names.index("ETA")


def test_no_sequence_when_capacity_fails():
    wm = WorkingMemory()
    wm.assert_fact("ctx", t=T, check_release=True, travel_time=tt)
    wm.assert_fact("vehicle", vehicle=veh(capacity=1))
    wm.assert_fact("order", order=order("A", 2, demand=3))
    _ENGINE.run(wm)
    assert not wm.facts("capacity_ok") and not wm.facts("sequence")


def test_without_travel_times_windows_are_not_checked_and_trace_says_so():
    r = run_feasibility_engine(veh(), [order("A", 5, tw=(0, 1))])
    assert r["feasible"] and any("TODO(R4/R5)" in line for line in r["trace"])


# R1's real models and R4's adapter
def test_with_r1_models():
    from src.sim.models import Order as SimOrder, Vehicle as SimVehicle

    v = SimVehicle("V1", depot_node=0, capacity=10, current_node=0, load=6.0)
    a = SimOrder("a", 3, 3, priority=2, tw_start=T, tw_end=T + 400)
    assert feasible(v, [a], tt, t_now=T)[0]
    assert violated_rules(feasible(v, [a, SimOrder("b", 4, 2)], tt, t_now=T)[1]) == [
        "KR-1"
    ]  # 6+3+2 > 10
    v.allowed_road_classes = ["primary"]
    assert road_allowed(v, 1, 2, {"road_class": "primary"}, T)[0]
    assert not road_allowed(v, 1, 2, {"road_class": "secondary"}, T)[0]


def test_r4_adapter_accepts_run_feasibility_engine():
    from src.allocation.cost_model import adapt_r3_feasibility
    from src.sim.models import Order as SimOrder, Vehicle as SimVehicle

    hook = adapt_r3_feasibility(run_feasibility_engine)
    ok, trace = hook(SimVehicle("V", 0, 5, 0), [SimOrder("o", 1, 3)])
    assert ok and trace[-1] == "FEASIBLE: o"
    ok, trace = hook(SimVehicle("V", 0, 5, 0, load=4.0), [SimOrder("o", 1, 3)])
    assert not ok and "KR-1" in trace[-1]


# road_allowed: KR-4 closure, KR-3 road class, KR-6 zone
large = veh(
    id="L1", vehicle_class="large", allowed_road_classes=ALL_ROAD_CLASSES - NARROW_ROAD_CLASSES
)


def test_kr4():
    assert road_allowed(veh(), 1, 2, {"highway": "primary"}, T)[0]
    ok, why = road_allowed(
        veh(), 1, 2, {"highway": "primary"}, T, is_blocked=lambda u, v, t: (u, v) == (1, 2)
    )
    assert not ok and why.startswith("KR-4")


def test_kr3():
    assert road_allowed(large, 1, 2, {"highway": "secondary"}, T)[0]
    ok, why = road_allowed(large, 1, 2, {"highway": "residential"}, T)
    assert not ok and why.startswith("KR-3")
    assert road_allowed(veh(), 1, 2, {"highway": "residential"}, T)[0]  # small vehicle is fine


def test_kr3_osmnx_list_uses_most_restrictive():
    assert not road_allowed(large, 1, 2, {"highway": ["primary", "residential"]}, T)[0]


def test_kr6():
    z = Zone("old_city", frozenset({2}), start=T, end=T + 3600)
    assert not road_allowed(large, 1, 2, {"highway": "primary"}, T + 100, zones=[z])[0]
    assert road_allowed(large, 1, 2, {"highway": "primary"}, T + 4000, zones=[z])[0]  # after hours
    assert road_allowed(veh(), 1, 2, {"highway": "primary"}, T + 100, zones=[z])[0]  # small vehicle

