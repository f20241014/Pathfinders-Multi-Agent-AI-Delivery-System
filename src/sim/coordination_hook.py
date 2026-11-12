"""R5's trigger after every local replan (R7, Week 5).

AgentPlanner (full mode) calls ``hook(vehicle_id, route, routes, t)`` once
after each local replan. ``TriggerCoordination`` is that hook, built only from
R5's public functions in src/coordination:

1. Turn every vehicle's Route (nodes + planned ETAs) into R5's VehicleRoute,
   from where each vehicle is now (nodes already passed are dropped).
2. Find road-slot conflicts with ``prepare_occupancies`` + ``detect_conflicts``
   and keep the ones that involve the vehicle that just replanned.
3. Skip a conflict negotiated less than ``rate_limit_s`` ago (same road, same
   vehicles), so one conflict is not re-negotiated at every event.
4. Ask the trigger (``should_negotiate``; e.g. ThresholdTrigger(tau)). If it
   fires, run R5's Vickrey auction. Bids use the real cost of yielding:
   priority weight x min(detour extra time from D* Lite, waiting time).
5. Each loser yields: if its detour costs no more than waiting, it detours
   (``AgentPlanner.yield_road``: one replan, which does not call this hook
   again). Otherwise it should wait; R1's simulator cannot hold a vehicle back
   yet, so the wait is only logged (``negotiation_result.actions``).

Messages are counted with R5's MessageCounter (3 per vehicle per auction,
D7) and logged as negotiation_request / _response / _result rows, the event
contract R2's multipane viewer reads (docs/multipane_viz.md).
"""

import math
from typing import Any, Dict, Optional, Tuple

from src.coordination.conflict import VehicleRoute, detect_conflicts, prepare_occupancies
from src.coordination.messages import MessageCounter
from src.coordination.negotiation import VirtualCreditBudget, run_vickrey_auction
from src.coordination.trigger import TriggerPolicy

MIN_EDGE_S = 1e-6        # R5's occupancy check needs positive edge times


def to_vehicle_route(vid: str, route, t: float, priority_weight: float = 1.0,
                     detour_extra_time: float = 0.0) -> Optional[VehicleRoute]:
    """R5's VehicleRoute for the part of a Route still ahead at time t."""
    nodes, times = list(route.nodes), list(route.expected_times)
    if len(nodes) < 2 or len(times) != len(nodes):
        return None
    i = 0                                   # last node reached by time t
    while i + 1 < len(nodes) and times[i + 1] <= t:
        i += 1
    nodes, times = nodes[i:], times[i:]
    keep_n, keep_t = [nodes[0]], [times[0]]
    for n, tt in zip(nodes[1:], times[1:]):
        if n != keep_n[-1]:                 # no self-loops (repeated stop)
            keep_n.append(n)
            keep_t.append(tt)
    if len(keep_n) < 2:
        return None
    travel = {}
    for a, b, ta, tb in zip(keep_n, keep_n[1:], keep_t, keep_t[1:]):
        travel[(a, b)] = max(tb - ta, MIN_EDGE_S)
    return VehicleRoute(vid, keep_n, max(keep_t[0], 0.0), travel,
                        priority_weight=priority_weight,
                        detour_extra_time=detour_extra_time)


class TriggerCoordination:
    """Coordination hook for AgentPlanner(mode="full")."""

    def __init__(self, trigger: TriggerPolicy, edge_capacities: Optional[Dict] = None,
                 rate_limit_s: float = 60.0, initial_credits: float = 100.0):
        self.trigger = trigger
        self.edge_capacities = edge_capacities or {}
        self.rate_limit_s = float(rate_limit_s)
        self.initial_credits = float(initial_credits)
        self.counter = MessageCounter()
        self.budgets: Dict[str, VirtualCreditBudget] = {}
        self._last: Dict[Tuple[Any, frozenset], float] = {}
        self.planner = None
        self.env = None
        self.auctions = 0
        self.rate_limited = 0
        self.not_triggered = 0

    def bind(self, planner) -> None:
        """Called by AgentPlanner: gives access to agents, env and yield_road."""
        self.planner = planner
        self.env = planner.env

    # -- helpers ---------------------------------------------------------
    def priority_weight(self, vid: str) -> float:
        """Highest priority (1-3) among the vehicle's undelivered orders."""
        orders = self.planner.pending_orders(vid) if self.planner else []
        return float(max((getattr(o, "priority", 1) for o in orders), default=1))

    def _edge_id(self, u, v):
        world = getattr(self.env, "world", None)
        try:
            return [u, v, world.edge_key(u, v)]
        except Exception:
            return [u, v]

    def _log(self, event: str, payload: dict, agent_id: str = "env") -> None:
        if self.env is not None:
            self.env.log_event(event, payload, agent_id=agent_id)

    # -- the hook --------------------------------------------------------
    def __call__(self, vid: str, route, routes: Dict[str, Any], t: float) -> int:
        vroutes = {}
        for other, r in routes.items():
            vr = to_vehicle_route(other, r, t, self.priority_weight(other))
            if vr is not None:
                vroutes[other] = vr
        if vid not in vroutes:
            return 0
        conflicts = detect_conflicts(prepare_occupancies(vroutes.values()),
                                     self.edge_capacities)
        sent = 0
        for c in conflicts:
            if vid not in c.vehicles:
                continue
            key = (c.edge, frozenset(c.vehicles))
            if t - self._last.get(key, -math.inf) < self.rate_limit_s:
                self.rate_limited += 1
                continue
            if not self.trigger.should_negotiate(vroutes[vid], vroutes, t, conflict=c):
                self.not_triggered += 1
                continue
            self._last[key] = t
            sent += self._negotiate(c, vroutes, t)
        return sent

    def _negotiate(self, c, vroutes: Dict[str, VehicleRoute], t: float) -> int:
        u, v = c.edge
        wait_s = max(c.duration, 0.0)
        bids, detours = [], {}
        for x in sorted(c.vehicles):
            agent = self.planner.agents.get(x) if self.planner else None
            detour = agent.detour_extra(u, v) if agent is not None else math.inf
            detours[x] = detour
            base = vroutes[x]
            bids.append(VehicleRoute(base.vehicle_id, base.nodes, base.start_time,
                                     base.travel_times, base.priority_weight,
                                     min(detour, wait_s)))
            self.budgets.setdefault(x, VirtualCreditBudget(x, self.initial_credits))
        before = self.counter.total_messages
        winner, losers, price = run_vickrey_auction(bids, self.budgets, self.counter)
        n = self.counter.total_messages - before
        self.auctions += 1
        edge = self._edge_id(u, v)
        for x in sorted(c.vehicles):
            self._log("negotiation_request", {"count": 1, "edge": edge}, agent_id=x)
            self._log("negotiation_response", {"count": 1, "edge": edge}, agent_id=x)
        actions = {}
        for x in losers if winner is not None else []:
            if detours[x] <= wait_s and self.planner.yield_road(x, u, v, c.overlap_end, t):
                actions[x] = "detour"
            else:
                actions[x] = "wait"         # not enforced: R1's sim cannot hold a vehicle
        self._log("negotiation_result", {
            "count": len(c.vehicles),
            "edge": edge,
            "vehicles": sorted(c.vehicles),
            "winner": winner,
            "price": price,
            "ttc": c.time_to_conflict(t),
            "actions": actions,
        })
        return n


__all__ = ["TriggerCoordination", "to_vehicle_route"]
