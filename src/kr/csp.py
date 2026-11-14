"""
R3 · CSP for order -> vehicle assignment feasibility (Week 3).

Formulation (say exactly this in the report and the viva)
    Variables   X_o, one per order o in the batch being assigned
    Domains     D_o = vehicles v that could serve o on top of what v already has (committed[v]):
                unary checks KR-11 release, KR-1 capacity, KR-8 windows, KR-10 shift, reachability
    Binary      for orders o, p and a vehicle v in both domains:
                (X_o = v and X_p = v) is allowed only if v can serve committed[v] + {o, p}
                -> the constraint graph AC-3 works on
    Global      everything assigned to v must be serviceable in SOME stop order (capacity +
                windows + shift). Checked exactly whenever a value is assigned (n-ary constraint).

Times are seconds since midnight (default start 06:00); "no time window" is R1's default pair
(0.0, 86400.0), read through ontology.tw_of() like everywhere else in R3's code.

Search
    backtracking; variable order MRV (fewest values left), ties broken by degree;
    value order LCV (value that removes fewest options from neighbours first);
    forward checking after each assignment; AC-3 once before search, and optionally after every
    assignment (MAC = maintaining arc consistency). Every option can be switched off so the
    benchmark can measure what each one prunes.

Why it is sound: the binary constraint is a NECESSARY condition of the global one (if v cannot
serve {o, p} it cannot serve any superset), so AC-3 never removes a value that appears in a
solution. tests/test_csp.py checks this by brute force.

Scale (guide pitfall): a global CSP over 300 orders x 20 vehicles is too slow. Use it on small
sub-problems: one new order (eligible_vehicles, the filter before bidding) or a batch of a few
orders after a disruption.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .ontology import SIM_START_S, position_of, shift_end_of, tw_of

TravelTime = Callable[[int, int, float], float]
EXACT_LIMIT = 9  # exact stop-order search up to this many stops (rules.py uses the same limit)


# ===================================================================== single-vehicle sequencing
def _serve(o, node, t, tt):
    """Arrive at o from node at time t. Returns (start_of_service, departure) or None if late."""
    arrival = t + tt(node, o.node, t)
    if math.isinf(arrival):
        return None
    tw = tw_of(o)
    start = max(arrival, tw[0] if tw else -math.inf, o.release_time)  # KR-7 wait
    if tw and start > tw[1]:  # KR-8
        return None
    return start, start + o.service_time  # KR-9


def _deadline(o):
    tw = tw_of(o)
    return tw[1] if tw else math.inf


def schedule_in_order(vehicle, seq, tt: TravelTime, t_now: float = SIM_START_S) -> bool:
    """Is this exact stop order feasible (windows + back by shift end)?"""
    t, node = t_now, position_of(vehicle)
    for o in seq:
        r = _serve(o, node, t, tt)
        if r is None:
            return False
        t, node = r[1], o.node
    return t + tt(node, vehicle.depot_node, t) <= shift_end_of(vehicle)


def find_sequence(vehicle, orders, tt: TravelTime, t_now: float = SIM_START_S):
    """Exact search for a stop order that meets every window and the shift end.

    Depth-first over stop orders, children tried earliest-deadline-first, with two prunings:
      * dominance: reaching the same (stops left, last stop) later than before can never help
        (waiting is allowed and travel times are FIFO, see R2's fifo_check)
      * look-ahead: if some remaining stop can no longer be reached before its deadline, stop
    Returns (list_of_orders or None, nodes_expanded).
    """
    orders = list(orders)
    n = len(orders)
    if n == 0:
        ok = t_now + tt(position_of(vehicle), vehicle.depot_node, t_now) <= shift_end_of(vehicle)
        return ([] if ok else None), 0
    order_idx = sorted(range(n), key=lambda i: (_deadline(orders[i]), orders[i].priority))
    best: dict = {}
    expanded = 0
    shift_end = shift_end_of(vehicle)

    def dfs(left: frozenset, node, last, t, path):
        nonlocal expanded
        if not left:
            return path if t + tt(node, vehicle.depot_node, t) <= shift_end else None
        key = (left, last)
        if best.get(key, math.inf) <= t:
            return None
        best[key] = t
        for i in left:  # look-ahead: every remaining stop must still be reachable in time
            if _serve(orders[i], node, t, tt) is None:
                return None
        for i in order_idx:
            if i not in left:
                continue
            r = _serve(orders[i], node, t, tt)
            if r is None:
                continue
            expanded += 1
            found = dfs(left - {i}, orders[i].node, i, r[1], path + [orders[i]])
            if found is not None:
                return found
        return None

    return dfs(frozenset(range(n)), position_of(vehicle), None, t_now, []), expanded


def set_feasible(
    vehicle, orders, tt: TravelTime, t_now: float = SIM_START_S, check_release=True
) -> bool:
    """Fast yes/no for 'vehicle can serve all of orders' (KR-1, KR-11, KR-8, KR-10, reachability).

    Exact up to EXACT_LIMIT stops; above that it tries priority-first and EDF orders only
    (a 'no' may then be a false negative, never a false 'yes').
    """
    orders = list(orders)
    if vehicle.load + sum(o.demand for o in orders) > vehicle.capacity:  # KR-1
        return False
    if check_release and any(o.release_time > t_now for o in orders):  # KR-11
        return False
    if len(orders) <= EXACT_LIMIT:
        return find_sequence(vehicle, orders, tt, t_now)[0] is not None
    for key in ((lambda o: (o.priority, _deadline(o))), (lambda o: (_deadline(o), o.priority))):
        if schedule_in_order(vehicle, sorted(orders, key=key), tt, t_now):
            return True
    return False


# ===================================================================== assignment CSP
@dataclass
class Stats:
    nodes: int = 0  # values tried in the search tree
    backtracks: int = 0
    global_checks: int = 0  # n-ary constraint evaluations (cache misses)
    ac3_revisions: int = 0
    ac3_removed: int = 0
    fc_removed: int = 0
    seconds: float = 0.0
    limit_hit: bool = False


@dataclass
class Result:
    assignment: Optional[dict]  # order_id -> vehicle_id, or None if no solution
    stats: Stats
    initial_domains: dict = field(default_factory=dict)
    rejected: dict = field(default_factory=dict)  # order_id with empty initial domain -> reason

    @property
    def feasible(self) -> bool:
        return self.assignment is not None


class AssignmentCSP:
    def __init__(
        self,
        vehicles,
        orders,
        travel_time: TravelTime,
        t_now: float = SIM_START_S,
        committed: Optional[dict] = None,
        check_release: bool = True,
    ):
        self.V = {v.id: v for v in vehicles}
        self.orders = list(orders)
        self.by_id = {o.id: o for o in self.orders}
        if len(self.by_id) != len(self.orders) or len(self.V) != len(list(vehicles)):
            raise ValueError("duplicate order or vehicle id")
        self.committed = {vid: list((committed or {}).get(vid, [])) for vid in self.V}
        self.tt, self.t_now, self.check_release = travel_time, t_now, check_release
        self.stats = Stats()
        self._cache: dict = {}
        self._load: Optional[dict] = None  # current partial assignment, used by MAC

    # ---------------------------------------------------------------- constraint checks
    def ok(self, vid, order_ids) -> bool:
        """Global constraint: can vid serve committed[vid] + these orders? (cached)"""
        key = (vid, frozenset(order_ids))
        if key not in self._cache:
            self.stats.global_checks += 1
            self._cache[key] = set_feasible(
                self.V[vid],
                self.committed[vid] + [self.by_id[i] for i in order_ids],
                self.tt,
                self.t_now,
                self.check_release,
            )
        return self._cache[key]

    def compatible(self, a, b, vid) -> bool:
        """Binary constraint between X_a and X_b for value vid.

        Before search: can vid serve {a, b}? During search (MAC) the orders already assigned to vid
        are included, which is the same constraint conditioned on the current partial assignment.
        """
        already = self._load[vid] if self._load is not None else []
        return self.ok(vid, tuple(already) + (a, b))

    def unary_domains(self):
        doms, rejected = {}, {}
        for o in self.orders:
            doms[o.id] = [vid for vid in self.V if self.ok(vid, (o.id,))]
            if not doms[o.id]:
                rejected[o.id] = (
                    "no vehicle can serve it alone (KR-1/KR-8/KR-10/KR-11 or unreachable)"
                )
        return doms, rejected

    def _neighbours(self, doms):
        nb = {a: set() for a in doms}
        ids = list(doms)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:  # noqa: E203 (black's slice style)
                if set(doms[a]) & set(doms[b]):
                    nb[a].add(b)
                    nb[b].add(a)
        return nb

    # ---------------------------------------------------------------- AC-3
    def revise(self, doms, xi, xj) -> bool:
        """Remove values of xi with no support in xj.

        Support for v: any w != v in xj, or w == v if (xi, xj) may share v.
        """
        self.stats.ac3_revisions += 1
        removed = False
        for v in list(doms[xi]):
            if any(w != v for w in doms[xj]):
                continue
            if v in doms[xj] and self.compatible(xi, xj, v):
                continue
            doms[xi].remove(v)
            self.stats.ac3_removed += 1
            removed = True
        return removed

    def ac3(self, doms, nb, queue=None) -> bool:
        """AC-3 (Mackworth 1977). Returns False if some domain becomes empty.

        Complexity O(e * d^3) for e arcs and domain size d: each arc is re-queued at most d times
        and each revise costs O(d^2) checks.
        """
        queue = list(queue) if queue is not None else [(a, b) for a in nb for b in nb[a]]
        while queue:
            xi, xj = queue.pop(0)
            if self.revise(doms, xi, xj):
                if not doms[xi]:
                    return False
                queue.extend((xk, xi) for xk in nb[xi] if xk != xj)
        return True

    # ---------------------------------------------------------------- search
    def solve(self, mrv=True, fc=True, ac3=True, mac=False, lcv=True, node_limit=200_000) -> Result:
        t0 = time.perf_counter()
        doms, rejected = self.unary_domains()
        initial = {k: list(v) for k, v in doms.items()}
        if rejected:
            self.stats.seconds = time.perf_counter() - t0
            return Result(None, self.stats, initial, rejected)
        nb = self._neighbours(doms)
        if ac3 and not self.ac3(doms, nb):
            self.stats.seconds = time.perf_counter() - t0
            return Result(None, self.stats, initial, {})
        static_order = [o.id for o in self.orders]
        assign: dict = {}
        load: dict = {vid: [] for vid in self.V}
        self._load = load

        def select(doms):
            un = [x for x in static_order if x not in assign]
            if not mrv:
                return un[0]
            return min(un, key=lambda x: (len(doms[x]), -sum(1 for y in nb[x] if y not in assign)))

        def values(x, doms):
            if not lcv:
                return list(doms[x])

            def cost(v):  # how many neighbour options would v rule out
                return sum(
                    1
                    for y in nb[x]
                    if y not in assign and v in doms[y] and not self.ok(v, load[v] + [x, y])
                )

            return sorted(doms[x], key=cost)

        def bt(doms):
            if len(assign) == len(static_order):
                return True
            if self.stats.nodes >= node_limit:
                self.stats.limit_hit = True
                return False
            x = select(doms)
            for v in values(x, doms):
                if self.stats.limit_hit:  # stop the whole search, not just this level
                    return False
                if self.stats.nodes >= node_limit:
                    self.stats.limit_hit = True
                    return False
                self.stats.nodes += 1
                if not self.ok(v, load[v] + [x]):  # global constraint
                    continue
                assign[x] = v
                load[v].append(x)
                new = {k: list(d) for k, d in doms.items()}
                new[x] = [v]
                good = True
                if fc:
                    for y in nb[x]:
                        if y in assign or v not in new[y]:
                            continue
                        if not self.ok(v, load[v] + [y]):
                            new[y].remove(v)
                            self.stats.fc_removed += 1
                            if not new[y]:
                                good = False
                                break
                if good and mac:  # propagate among the unassigned orders
                    un = [y for y in nb if y not in assign]
                    good = self.ac3(
                        new,
                        {y: {z for z in nb[y] if z not in assign} for y in un},
                        [(y, z) for y in un for z in nb[y] if z not in assign],
                    )
                if good and bt(new):
                    return True
                del assign[x]
                load[v].remove(x)
            self.stats.backtracks += 1
            return False

        found = bt(doms)
        self._load = None
        self.stats.seconds = time.perf_counter() - t0
        return Result(dict(assign) if found else None, self.stats, initial, {})


# ===================================================================== filter before bidding
def eligible_vehicles(
    order,
    vehicles,
    travel_time: TravelTime,
    t_now: float = SIM_START_S,
    committed: Optional[dict] = None,
    check_release: bool = True,
    explain=False,
):
    """Which vehicles may bid on a new order? (one-variable CSP: its domain after the unary checks)

    Returns (eligible_ids, reasons) where reasons[vid] is the rule trace for each rejected vehicle
    (only filled when explain=True, because explanations run the slower rule engine).
    """
    committed = committed or {}
    eligible, reasons = [], {}
    for v in vehicles:
        orders = list(committed.get(v.id, [])) + [order]
        if set_feasible(v, orders, travel_time, t_now, check_release):
            eligible.append(v.id)
        elif explain:
            from .rules import feasible

            reasons[v.id] = feasible(v, orders, travel_time, t_now, check_release)[1]
    return eligible, reasons


def solve_batch(
    vehicles,
    orders,
    travel_time: TravelTime,
    t_now: float = SIM_START_S,
    committed: Optional[dict] = None,
    **opts,
) -> Result:
    """Convenience wrapper: is there an assignment of these orders to these vehicles?"""
    return AssignmentCSP(
        vehicles, orders, travel_time, t_now, committed, opts.pop("check_release", True)
    ).solve(**opts)