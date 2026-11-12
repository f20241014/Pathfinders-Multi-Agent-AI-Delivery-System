"""
R3 · Delivery knowledge base: the rules in docs/kr_ontology_rules.md as forward-chaining rules.

Public API
    run_feasibility_engine(vehicle, orders, travel_time=None, t_now=None) -> dict
        {"feasible": bool, "trace": [...], "violated": ["KR-1", ...], "sequence": [order ids]}
        R4 plugs it in with adapt_r3_feasibility(run_feasibility_engine).
    feasible(vehicle, orders, travel_time=None, t_now=SIM_START_S) -> (bool, trace)
    road_allowed(vehicle, u, v, edge_data, t, zones=(), is_blocked=None) -> (bool, reason)
        edge filter for R2's / R7's planners

How the rules chain (each rule only fires on facts other rules derived):
    vehicle + orders --LOAD--> load_total --KR-1--> capacity_ok
    orders --KR-11--> release_ok
    orders --SERVICE--> service_total --KR-10a--> shift_duration_ok
    capacity_ok + release_ok + shift_duration_ok --KR-13--> sequence
    sequence + travel_time --ETA (KR-7, KR-9)--> stop, return --KR-8 / KR-10--> violations
    violation on a priority sequence --KR-13x--> EDF sequence --KR-13y--> exact search
Conflict resolution = salience: legality > physical limits > sequencing > timing > overrides.

Without travel times (R4's two-argument call) the arrival-window checks KR-8 and KR-10 cannot run:
the trace says so. TODO(R4/R5): pass travel_time so they run.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Optional

from .engine import Activation, Engine, Rule, WorkingMemory
from .ontology import (
    NARROW_ROAD_CLASSES,
    SIM_START_S,
    Zone,
    allowed_classes_of,
    class_of,
    position_of,
    shift_end_of,
    tw_of,
)

TravelTime = Callable[[int, int, float], float]  # travel_time(u, v, depart_t) -> s (inf = no path)
HARD = "violation"
EXACT_LIMIT = 9  # exact stop-order search up to this many stops (worst case grows like n!)


def sort_orders_by_priority(orders):
    """Express first, then standard, then economy; earlier deadline first within a tier (KR-13)."""
    return sorted(orders, key=lambda o: (o.priority, _deadline(o), o.id))


def _deadline(o) -> float:
    tw = tw_of(o)
    return tw[1] if tw else math.inf


def _violations(wm, rule=None):
    return [f for f in wm.facts(HARD) if rule is None or f["rule"] == rule]


def _orders(wm):
    return [f["order"] for f in wm.facts("order")]


def _ctx(wm):
    return wm.one("ctx")


# ---------------------------------------------------------------- KR-11 release time
def _m_release(wm):
    if not wm.facts("release_ok") and not _violations(wm, "KR-11"):
        yield Activation(("KR-11",), None, 0)


def _a_release(wm, _):
    c = _ctx(wm)
    if not c["check_release"]:
        wm.assert_fact("release_ok")
        return None
    late = [o for o in _orders(wm) if o.release_time > c["t"]]
    if late:
        for o in late:
            wm.assert_fact(
                HARD,
                rule="KR-11",
                seq=None,
                msg=f"{o.id} released at {o.release_time:.0f}s > now {c['t']:.0f}s",
            )
        return "FAIL not released yet: " + ", ".join(o.id for o in late)
    wm.assert_fact("release_ok")
    return None


# ---------------------------------------------------------------- KR-1 capacity
def _m_load(wm):
    if not wm.facts("load_total"):
        yield Activation(("LOAD",), None, 0)


def _a_load(wm, _):
    veh = wm.one("vehicle")["vehicle"]
    total = veh.load + sum(o.demand for o in _orders(wm))
    wm.assert_fact("load_total", total=total)
    return f"load_total = {veh.load:g} on board + {total - veh.load:g} new = {total:g}"


def _m_capacity(wm):
    for f in wm.facts("load_total"):
        yield Activation(("KR-1", f["_id"]), f, f["_id"])


def _a_capacity(wm, f):
    cap = wm.one("vehicle")["vehicle"].capacity
    if f["total"] > cap:
        wm.assert_fact(HARD, rule="KR-1", seq=None, msg=f"load {f['total']:g} > capacity {cap:g}")
        return f"FAIL load {f['total']:g}/{cap:g}"
    wm.assert_fact("capacity_ok")
    return f"ok load {f['total']:g}/{cap:g}"


# ---------------------------------------------------------------- KR-10a shift duration
def _m_service(wm):
    if not wm.facts("service_total"):
        yield Activation(("SERVICE",), None, 0)


def _a_service(wm, _):
    total = sum(o.service_time for o in _orders(wm))
    wm.assert_fact("service_total", total=total)
    return None


def _m_shift_duration(wm):
    for f in wm.facts("service_total"):
        yield Activation(("KR-10a", f["_id"]), f, f["_id"])


def _a_shift_duration(wm, f):
    """check_shift_duration: even with zero travel, all service must fit before shift_end."""
    end = shift_end_of(wm.one("vehicle")["vehicle"])
    finish = _ctx(wm)["t"] + f["total"]
    if finish > end:
        wm.assert_fact(
            HARD,
            rule="KR-10a",
            seq=None,
            msg=f"service alone ends {finish:.0f}s > shift_end {end:.0f}s",
        )
        return f"FAIL service alone ends {finish:.0f}s > shift_end {end:.0f}s"
    wm.assert_fact("shift_duration_ok")
    return None


# ---------------------------------------------------------------- KR-13 sequencing (soft)
def _m_sequence(wm):
    ready = all(wm.facts(k) for k in ("capacity_ok", "release_ok", "shift_duration_ok"))
    if ready and not wm.facts("sequence"):
        yield Activation(("KR-13",), None, 0)


def _a_sequence(wm, _):
    orders = sort_orders_by_priority(_orders(wm))
    wm.assert_fact("sequence", ids=[o.id for o in orders], source="priority")
    msg = "sequence by priority tier: " + " -> ".join(o.id for o in orders)
    if _ctx(wm)["travel_time"] is None:
        msg += " (no travel times: KR-8/KR-10 arrival checks not run, TODO(R4/R5))"
    return msg


# ---------------------------------------------------------------- KR-7 wait, KR-9 departure
def _m_eta(wm):
    if _ctx(wm)["travel_time"] is None:
        return
    for s in wm.facts("sequence"):
        if not wm.exists("eta_done", seq=s["_id"]):
            yield Activation(("ETA", s["_id"]), s, s["_id"])


def _a_eta(wm, seq):
    veh = wm.one("vehicle")["vehicle"]
    c = _ctx(wm)
    tt: TravelTime = c["travel_time"]
    by_id = {o.id: o for o in _orders(wm)}
    t, node = c["t"], position_of(veh)
    waits = []
    for oid in seq["ids"]:
        o = by_id[oid]
        arrival = t + tt(node, o.node, t)
        if math.isinf(arrival):
            wm.assert_fact(
                HARD, rule="REACH", seq=seq["_id"], msg=f"{oid} unreachable for {veh.id}"
            )
            wm.assert_fact("eta_done", seq=seq["_id"])
            return f"FAIL {oid} unreachable (road rules leave no path)"
        tw = tw_of(o)
        start = max(arrival, tw[0] if tw else -math.inf, o.release_time)  # KR-7 wait
        if start > arrival:
            waits.append(f"{oid} waits {start - arrival:.0f}s")
        depart = start + o.service_time  # KR-9
        wm.assert_fact("stop", seq=seq["_id"], order=o, arrival=arrival, start=start, depart=depart)
        t, node = depart, o.node
    back = t + tt(node, veh.depot_node, t)
    wm.assert_fact("return", seq=seq["_id"], t=back)
    wm.assert_fact("eta_done", seq=seq["_id"])
    return f"KR-7/KR-9 ETAs for [{', '.join(seq['ids'])}], back at depot {back:.0f}s" + (
        f" ({'; '.join(waits)})" if waits else ""
    )


# ---------------------------------------------------------------- KR-8 window end, KR-10 shift end
def _m_tw(wm):
    for s in wm.facts("stop"):
        if tw_of(s["order"]):
            yield Activation(("KR-8", s["_id"]), s, s["_id"])


def _a_tw(wm, s):
    o = s["order"]
    end = tw_of(o)[1]
    if s["start"] > end:
        wm.assert_fact(
            HARD,
            rule="KR-8",
            seq=s["seq"],
            msg=f"{o.id} starts {s['start']:.0f}s > tw_end {end:.0f}s",
        )
        return f"FAIL {o.id} service starts {s['start']:.0f}s > tw_end {end:.0f}s"
    return None


def _m_shift(wm):
    for r in wm.facts("return"):
        yield Activation(("KR-10", r["_id"]), r, r["_id"])


def _a_shift(wm, r):
    end = shift_end_of(wm.one("vehicle")["vehicle"])
    if r["t"] > end:
        wm.assert_fact(
            HARD, rule="KR-10", seq=r["seq"], msg=f"back {r['t']:.0f}s > shift_end {end:.0f}s"
        )
        return f"FAIL back at depot {r['t']:.0f}s > shift_end {end:.0f}s"
    return f"ok back at depot by {r['t']:.0f}s" + (
        f" (shift_end {end:.0f}s)" if math.isfinite(end) else ""
    )


# ---------------------------------------------------------------- KR-13x / KR-13y overrides
def _replace_sequence(wm, old, ids, source):
    for f in list(wm.facts()):  # drop everything derived from the old sequence
        if f.get("seq") == old["_id"]:
            wm.retract(f["_id"])
    wm.retract(old["_id"])
    wm.assert_fact("sequence", ids=ids, source=source)


def _time_failures(wm, s):
    return [v for v in _violations(wm) if v["seq"] == s["_id"] and v["rule"] in ("KR-8", "KR-10")]


def _m_override(wm):
    for s in wm.facts("sequence"):
        if s["source"] == "priority" and _time_failures(wm, s):
            yield Activation(("KR-13x", s["_id"]), s, s["_id"])


def _a_override(wm, s):
    who = ", ".join(sorted({v["rule"] for v in _time_failures(wm, s)}))
    orders = sorted(_orders(wm), key=lambda o: (_deadline(o), o.priority, o.id))
    _replace_sequence(wm, s, [o.id for o in orders], "edf")
    return f"KR-13 overridden by {who}: retry earliest-deadline-first " + " -> ".join(
        o.id for o in orders
    )


def _m_exact(wm):
    for s in wm.facts("sequence"):
        if s["source"] == "edf" and len(s["ids"]) <= EXACT_LIMIT and _time_failures(wm, s):
            yield Activation(("KR-13y", s["_id"]), s, s["_id"])


def _a_exact(wm, s):
    seq, expanded = _find_sequence(
        wm.one("vehicle")["vehicle"], _orders(wm), _ctx(wm)["travel_time"], _ctx(wm)["t"]
    )
    if seq is None:
        n = len(s["ids"])
        return f"exact search over {n} stops ({expanded} nodes): no order meets every window"
    _replace_sequence(wm, s, [o.id for o in seq], "exact")
    return f"exact search ({expanded} nodes) found " + " -> ".join(o.id for o in seq)


def _serve(o, node, t, tt):
    arrival = t + tt(node, o.node, t)
    if math.isinf(arrival):
        return None
    tw = tw_of(o)
    start = max(arrival, tw[0] if tw else -math.inf, o.release_time)
    if tw and start > tw[1]:
        return None
    return start + o.service_time


def _find_sequence(vehicle, orders, tt, t_now):
    """Depth-first over stop orders, earliest deadline first, with dominance pruning.

    Returns (orders in a feasible order, or None; nodes expanded). The Week 3 CSP reuses this idea.
    """
    n = len(orders)
    idx = sorted(range(n), key=lambda i: (_deadline(orders[i]), orders[i].priority))
    best, expanded = {}, 0
    end = shift_end_of(vehicle)

    def dfs(left, node, last, t, path):
        nonlocal expanded
        if not left:
            return path if t + tt(node, vehicle.depot_node, t) <= end else None
        if best.get((left, last), math.inf) <= t:
            return None
        best[(left, last)] = t
        for i in idx:
            if i in left:
                depart = _serve(orders[i], node, t, tt)
                if depart is not None:
                    expanded += 1
                    found = dfs(left - {i}, orders[i].node, i, depart, path + [orders[i]])
                    if found is not None:
                        return found
        return None

    return dfs(frozenset(range(n)), position_of(vehicle), None, t_now, []), expanded


RULES = [
    Rule("KR-11", "No order is served before its release_time", 100, _m_release, _a_release),
    Rule("LOAD", "Derive load_total", 95, _m_load, _a_load),
    Rule("KR-1", "load_total <= capacity", 90, _m_capacity, _a_capacity),
    Rule("SERVICE", "Derive service_total", 85, _m_service, _a_service),
    Rule("KR-10a", "Service alone fits before shift_end", 80, _m_shift_duration, _a_shift_duration),
    Rule("KR-13", "Express stops before standard/economy (soft)", 50, _m_sequence, _a_sequence),
    Rule("ETA", "Derive arrival/start/departure (KR-7 wait, KR-9 service)", 40, _m_eta, _a_eta),
    Rule("KR-8", "Service starts no later than tw_end", 30, _m_tw, _a_tw),
    Rule("KR-10", "Back at depot by shift_end", 30, _m_shift, _a_shift),
    Rule(
        "KR-13x", "Hard time rules override the priority preference", 20, _m_override, _a_override
    ),
    Rule(
        "KR-13y", "If EDF also fails, search every stop order (small sets)", 10, _m_exact, _a_exact
    ),
]
_ENGINE = Engine(RULES)


def run_feasibility_engine(
    vehicle,
    orders: Iterable,
    travel_time: Optional[TravelTime] = None,
    t_now: Optional[float] = None,
    check_release: Optional[bool] = None,
) -> dict:
    """Run the rule base on 'vehicle takes all of orders' (on top of vehicle.load).

    t_now: seconds since midnight. If None (R4's two-argument call) the check starts at 06:00 and
    skips KR-11, because the caller has no clock; service still waits for release_time.
    """
    orders = list(orders)
    if check_release is None:
        check_release = t_now is not None
    t = SIM_START_S if t_now is None else float(t_now)
    wm = WorkingMemory()
    wm.assert_fact("ctx", t=t, check_release=check_release, travel_time=travel_time)
    wm.assert_fact("vehicle", vehicle=vehicle)
    for o in orders:
        wm.assert_fact("order", order=o)
    trace = _ENGINE.run(wm)
    bad = _violations(wm)
    seq = wm.one("sequence")
    if bad:
        trace.append("INFEASIBLE: " + "; ".join(f"{v['rule']} {v['msg']}" for v in bad))
    else:
        trace.append(
            "FEASIBLE: " + (" -> ".join(seq["ids"]) if seq and seq["ids"] else "(no orders)")
        )
    return {
        "feasible": not bad,
        "trace": trace,
        "violated": sorted({v["rule"] for v in bad}),
        "sequence": [] if bad or not seq else list(seq["ids"]),
    }


def feasible(
    vehicle,
    orders: Iterable,
    travel_time: Optional[TravelTime] = None,
    t_now: float = SIM_START_S,
    check_release: bool = True,
):
    """(ok, trace) version of run_feasibility_engine."""
    r = run_feasibility_engine(vehicle, orders, travel_time, t_now, check_release)
    return r["feasible"], r["trace"]


def violated_rules(trace: list[str]) -> list[str]:
    """Rule ids that blocked a check, read back from a trace (for rejection reasons)."""
    if not trace or not trace[-1].startswith("INFEASIBLE"):
        return []
    return sorted(
        {part.strip().split(" ")[0] for part in trace[-1].split(":", 1)[1].split(";")}
    )


# ---------------------------------------------------------------- road rules for planners
def _road_class(edge_data: dict) -> str:
    h = edge_data.get("road_class") or edge_data.get(
        "highway", "unclassified"
    )  # R2 adds road_class
    if isinstance(h, (list, tuple)):  # OSMnx keeps a list when simplification merged edges
        narrow = [c for c in h if c in NARROW_ROAD_CLASSES]
        return narrow[0] if narrow else h[0]  # most restrictive class wins
    return h


def road_allowed(
    vehicle,
    u: int,
    v: int,
    edge_data: dict,
    t: float,
    zones: Iterable[Zone] = (),
    is_blocked: Optional[Callable[[int, int, float], bool]] = None,
):
    """Edge filter for A* / D* Lite: KR-4 closures, KR-3 road class, KR-6 zones.

    KR-5 (one-way) is enforced by the directed graph itself.

    A plain predicate, not the engine: planners call it for every edge they relax.
    Zone definitions come from the caller. TODO(R2): provide the zones of our map.
    """
    if is_blocked is not None and is_blocked(u, v, t):
        return False, "KR-4 edge closed"
    cls = _road_class(edge_data)
    if cls not in allowed_classes_of(vehicle):
        return False, f"KR-3 road class '{cls}' not allowed for {vehicle.id}"
    vclass = class_of(vehicle)
    for z in zones:
        if v in z.nodes and z.restricts(vclass, t):
            return False, f"KR-6 zone {z.id} closed to {vclass} vehicles now"
    return True, "ok"