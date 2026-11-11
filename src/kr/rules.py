"""
R3 · Delivery knowledge base: the rules from docs/kr_ontology_rules.md encoded as production rules.

Public API (frozen hand-offs):
    feasible(vehicle, orders, travel_time, t_now=0.0) -> (bool, trace)
        used by R4 before a vehicle bids, and by planners before inserting an order
    road_allowed(vehicle, u, v, edge_data, t, zones=(), is_blocked=None) -> (bool, reason)
        used by R2 / R7 as the edge filter inside A* and D* Lite

Salience (higher fires first) follows the conflict-resolution order in the rules doc:
    100 legality of the order (R11) > 90 physical limits (R01) > 50 sequencing (R13)
    > 40 timing (R07, R09) > 30 commitments (R08, R10) > 20 override of a preference (R13 by R08/R10)

Week 2 limitation (say so in the report): if the priority-first sequence breaks a window, we try ONE
fallback order (earliest deadline first). A set can be feasible in another order we never try.
The exact check is the Week 3 CSP; this rule-based check is the fast path.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Optional

from .engine import Activation, Engine, Rule, WorkingMemory
from .ontology import NARROW_ROAD_CLASSES, Order, Vehicle, Zone

TravelTime = Callable[[int, int, float], float]   # travel_time(from_node, to_node, depart_t) -> seconds (inf if unreachable)
HARD = "violation"


def _violations(wm, rule=None):
    return [f for f in wm.facts(HARD) if rule is None or f["rule"] == rule]


# ---------------------------------------------------------------- order legality
def _m_release(wm):
    now = wm.one("now")["t"]
    for f in wm.facts("order"):
        o = f["order"]
        yield Activation(("R11", f["_id"]), (o, now, o.release_time > now), f["_id"])


def _a_release(wm, b):
    o, now, bad = b
    if bad:
        wm.assert_fact(HARD, rule="R11", seq=None, msg=f"{o.id} released at {o.release_time:.0f}s > now {now:.0f}s")
        return f"FAIL {o.id} not released yet (release {o.release_time:.0f}s, now {now:.0f}s)"
    return None   # keep the trace short: only report releases that fail


# ---------------------------------------------------------------- capacity
def _m_capacity(wm):
    v = wm.one("vehicle")
    if v and not wm.facts("load"):
        yield Activation(("R01",), v["vehicle"], v["_id"])


def _a_capacity(wm, veh: Vehicle):
    total = veh.load + sum(f["order"].demand for f in wm.facts("order"))
    wm.assert_fact("load", total=total)
    if total > veh.capacity:
        wm.assert_fact(HARD, rule="R01", seq=None, msg=f"load {total} > capacity {veh.capacity}")
        return f"FAIL load {total}/{veh.capacity}"
    return f"ok load {total}/{veh.capacity}"


# ---------------------------------------------------------------- sequencing (soft preference)
def _priority_key(o: Order):
    return (o.priority, o.tw_end if o.has_tw else math.inf, o.id)


def _edf_key(o: Order):
    return (o.tw_end if o.has_tw else math.inf, o.priority, o.id)


def _m_sequence(wm):
    if not wm.facts("sequence") and not _violations(wm):
        yield Activation(("R13",), None, 0)


def _a_sequence(wm, _):
    orders = sorted((f["order"] for f in wm.facts("order")), key=_priority_key)
    wm.assert_fact("sequence", ids=[o.id for o in orders], source="priority")
    return "sequence by priority tier: " + " -> ".join(o.id for o in orders)


# ---------------------------------------------------------------- timing: R07 wait, R09 departure
def _m_eta(wm):
    for s in wm.facts("sequence"):
        if not wm.exists("eta_done", seq=s["_id"]):
            yield Activation(("ETA", s["_id"]), s, s["_id"])


def _a_eta(wm, seq):
    veh: Vehicle = wm.one("vehicle")["vehicle"]
    tt: TravelTime = wm.one("ctx")["travel_time"]
    by_id = {f["order"].id: f["order"] for f in wm.facts("order")}
    t, node = wm.one("now")["t"], veh.current_node
    waits = []
    for oid in seq["ids"]:
        o = by_id[oid]
        arrival = t + tt(node, o.node, t)
        if math.isinf(arrival):
            wm.assert_fact(HARD, rule="REACH", seq=seq["_id"], msg=f"{oid} unreachable for {veh.id}")
            wm.assert_fact("eta_done", seq=seq["_id"])
            return f"FAIL {oid} unreachable (road rules leave no path)"
        start = max(arrival, o.tw_start) if o.has_tw else arrival           # R07: wait for tw_start
        if start > arrival:
            waits.append(f"{oid} waits {start - arrival:.0f}s")
        depart = start + o.service_time                                       # R09
        wm.assert_fact("stop", seq=seq["_id"], order=o, arrival=arrival, start=start, depart=depart)
        t, node = depart, o.node
    back = t + tt(node, veh.depot_node, t)
    wm.assert_fact("return", seq=seq["_id"], t=back)
    wm.assert_fact("eta_done", seq=seq["_id"])
    return f"R07/R09 ETAs for [{', '.join(seq['ids'])}], back at depot {back:.0f}s" + (
        f" ({'; '.join(waits)})" if waits else ""
    )


# ---------------------------------------------------------------- commitments
def _m_tw(wm):
    for s in wm.facts("stop"):
        o = s["order"]
        if o.has_tw:
            yield Activation(("R08", s["_id"]), s, s["_id"])


def _a_tw(wm, s):
    o = s["order"]
    if s["start"] > o.tw_end:
        wm.assert_fact(HARD, rule="R08", seq=s["seq"], msg=f"{o.id} starts {s['start']:.0f}s > tw_end {o.tw_end:.0f}s")
        return f"FAIL {o.id} service starts {s['start']:.0f}s > tw_end {o.tw_end:.0f}s"
    return None


def _m_shift(wm):
    for r in wm.facts("return"):
        yield Activation(("R10", r["_id"]), r, r["_id"])


def _a_shift(wm, r):
    veh = wm.one("vehicle")["vehicle"]
    if r["t"] > veh.shift_end:
        wm.assert_fact(HARD, rule="R10", seq=r["seq"], msg=f"back {r['t']:.0f}s > shift_end {veh.shift_end:.0f}s")
        return f"FAIL back at depot {r['t']:.0f}s > shift_end {veh.shift_end:.0f}s"
    return f"ok back at depot by {r['t']:.0f}s (shift_end {veh.shift_end:.0f}s)"


# ---------------------------------------------------------------- R13 overridden by R08 / R10
def _m_override(wm):
    for s in wm.facts("sequence"):
        if s["source"] == "priority":
            bad = [v for v in _violations(wm) if v["seq"] == s["_id"] and v["rule"] in ("R08", "R10")]
            if bad:
                yield Activation(("R13x", s["_id"]), (s, bad), s["_id"])


def _a_override(wm, b):
    s, bad = b
    sid = s["_id"]
    for f in list(wm.facts()):                      # drop everything derived from the old sequence
        if f.get("seq") == sid:
            wm.retract(f["_id"])
    wm.retract(sid)
    orders = sorted((f["order"] for f in wm.facts("order")), key=_edf_key)
    wm.assert_fact("sequence", ids=[o.id for o in orders], source="edf")
    who = ", ".join(sorted({v["rule"] for v in bad}))
    return f"R13 overridden by {who}: retry earliest-deadline-first " + " -> ".join(o.id for o in orders)


RULES = [
    Rule("R11", "No order is assigned before its release_time", 100, _m_release, _a_release),
    Rule("R01", "Total demand <= vehicle capacity", 90, _m_capacity, _a_capacity),
    Rule("R13", "Express stops before standard/economy (soft)", 50, _m_sequence, _a_sequence),
    Rule("ETA", "Derive arrival/start/departure (R07 wait, R09 service)", 40, _m_eta, _a_eta),
    Rule("R08", "Service starts no later than tw_end", 30, _m_tw, _a_tw),
    Rule("R10", "Back at depot by shift_end", 30, _m_shift, _a_shift),
    Rule("R13x", "Hard time rules override the priority preference", 20, _m_override, _a_override),
]
_ENGINE = Engine(RULES)


def feasible(vehicle: Vehicle, orders: Iterable[Order], travel_time: TravelTime, t_now: float = 0.0):
    """Can `vehicle` serve all `orders` (on top of what it already carries) starting at t_now?

    Returns (ok, trace). trace lists the rules that fired, ending with the verdict and,
    if ok, the stop sequence to use.
    """
    orders = list(orders)
    wm = WorkingMemory()
    wm.assert_fact("now", t=t_now)
    wm.assert_fact("ctx", travel_time=travel_time)
    wm.assert_fact("vehicle", vehicle=vehicle)
    for o in orders:
        wm.assert_fact("order", order=o)
    trace = _ENGINE.run(wm)
    bad = _violations(wm)
    if bad:
        trace.append("INFEASIBLE: " + "; ".join(f"{v['rule']} {v['msg']}" for v in bad))
        return False, trace
    seq = wm.one("sequence")
    trace.append("FEASIBLE: " + (" -> ".join(seq["ids"]) if seq else "(no orders)"))
    return True, trace


def violated_rules(trace: list[str]) -> list[str]:
    """Rule ids that blocked a feasibility check (for R15 rejection reasons and Week 6 statistics)."""
    if not trace or not trace[-1].startswith("INFEASIBLE"):
        return []
    return sorted({part.strip().split(" ")[0] for part in trace[-1][len("INFEASIBLE:"):].split(";")})


# ---------------------------------------------------------------- road rules for planners
def _road_class(edge_data: dict) -> str:
    h = edge_data.get("highway", "unclassified")
    if isinstance(h, (list, tuple)):   # OSMnx keeps a list when simplification merged edges
        narrow = [c for c in h if c in NARROW_ROAD_CLASSES]
        return narrow[0] if narrow else h[0]   # most restrictive class wins
    return h


def road_allowed(
    vehicle: Vehicle,
    u: int,
    v: int,
    edge_data: dict,
    t: float,
    zones: Iterable[Zone] = (),
    is_blocked: Optional[Callable[[int, int, float], bool]] = None,
):
    """Edge filter for A* / D* Lite. Compiled from rules R04, R03, R06 (R05 one-way is the directed graph).

    Not run through the engine on purpose: A* calls this for every edge it relaxes, so it must be a
    plain predicate. The rule ids in the reason keep it traceable to the knowledge base.
    """
    if is_blocked is not None and is_blocked(u, v, t):
        return False, "R04 edge closed"
    cls = _road_class(edge_data)
    if cls not in vehicle.allowed_road_classes:
        return False, f"R03 road class '{cls}' not allowed for {vehicle.id}"
    for z in zones:
        if v in z.nodes and z.restricts(vehicle.vehicle_class, t):
            return False, f"R06 zone {z.id} closed to {vehicle.vehicle_class} vehicles now"
    return True, "ok"