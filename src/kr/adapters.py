"""
R3 · Glue between the knowledge base and the other modules (no logic of its own).

    r4_feasibility_hook(travel, now_fn=None)
        -> feasibility(vehicle, orders) -> (bool, trace) for R4's schedule(), ContractNet and
           CentralVRP, WITH travel times, so the window rules KR-8 / KR-10 run as well:
           ContractNet(travel, feasibility=r4_feasibility_hook(travel))
        (adapt_r3_feasibility(run_feasibility_engine) also works, but without travel times it can
         only check capacity, release and shift duration)
    travel_time_from_matrix(ttm, nodes, bucket_s=900)
        -> travel_time(u, v, t) for the rules / CSP from R2's TravelTimeMatrix
"""

from __future__ import annotations

import math

from .ontology import SIM_START_S
from .rules import feasible


def r4_feasibility_hook(travel, now_fn=None):
    """Wrap R3's rules as R4's feasibility callback.

    travel is R4's callback travel(vehicle, u, v) -> seconds (a snapshot, no time argument).
    now_fn (optional) returns the current simulation time in seconds since midnight (R1: env.now).
    Without it the check starts at 06:00 and skips KR-11 (R4's schedule already waits for
    release_time); R4's own schedule() still re-checks the windows after it.
    """

    def hook(vehicle, orders):
        def tt(u, v, _t):
            return travel(vehicle, u, v)

        if now_fn is None:
            return feasible(vehicle, orders, tt, t_now=SIM_START_S, check_release=False)
        return feasible(vehicle, orders, tt, t_now=float(now_fn()), check_release=True)

    return hook


def travel_time_from_matrix(ttm, nodes, bucket_s: float = 900.0):
    """travel_time(u, v, t) backed by R2's TravelTimeMatrix.

    nodes: every node the CSP may ask about (order nodes, depots, vehicle positions), so one cached
    Dijkstra row per (time bucket, source) covers all of them. Times are rounded down to bucket_s
    (default 15 min) so rows get reused; use the predicted-time cost factory for planning (D10).
    """
    targets = set(nodes)

    def tt(u, v, t):
        if u == v:
            return 0.0
        key_t = math.floor(t / bucket_s) * bucket_s
        return ttm.row(u, key_t, targets | {v})[v]

    return tt