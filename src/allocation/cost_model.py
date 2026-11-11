"""Shared feasibility, travel-only objective and snapshot vehicle state.

Load follows the existing simulator: accumulated demand, no depot unloading.
Time windows constrain service START; completion includes service duration.
"""
from dataclasses import dataclass, field
import math
from typing import Callable

from src.sim.models import Order, Vehicle


@dataclass
class VehicleState:
    vehicle: Vehicle
    orders: list[Order] = field(default_factory=list)
    available_at: float = 0.0


@dataclass
class Schedule:
    feasible: bool
    travel_seconds: float = math.inf
    arrivals: list[float] = field(default_factory=list)
    reason: str = ''


def validate(vehicles, orders):
    """Reject ambiguous identities or physically invalid inputs before solving."""
    if len({v.vehicle.id for v in vehicles}) != len(vehicles):
        raise ValueError('duplicate vehicle id')
    if len({o.id for o in orders}) != len(orders):
        raise ValueError('duplicate order id')
    for state in vehicles:
        v = state.vehicle
        if not all(math.isfinite(x) for x in (v.capacity, v.load, state.available_at)):
            raise ValueError('non-finite vehicle state')
        if not 0 <= v.load <= v.capacity:
            raise ValueError('invalid vehicle load')
    for o in orders:
        values = (o.demand, o.tw_start, o.tw_end, o.service_time, o.release_time)
        if not all(math.isfinite(x) for x in values):
            raise ValueError('non-finite order')
        if o.demand < 0 or o.service_time < 0 or o.tw_start > o.tw_end:
            raise ValueError('invalid demand, service time or window')
        if o.priority not in (1, 2, 3):
            raise ValueError('priority must be 1, 2 or 3')


def schedule(state: VehicleState, orders: list[Order], travel: Callable,
             now: float = 0, feasibility=None) -> Schedule:
    """Evaluate an open route; callback travel(vehicle,u,v) returns snapshot seconds.

    Optional R3 callback feasible(vehicle, orders) returns (bool, explanation).
    """
    validate([state], orders)
    if state.vehicle.load + sum(o.demand for o in orders) > state.vehicle.capacity:
        return Schedule(False, reason='capacity')
    if feasibility is not None:
        ok, trace = feasibility(state.vehicle, orders)
        if not ok:
            return Schedule(False, reason=str(trace))
    clock = max(now, state.available_at)
    node = state.vehicle.current_node
    total = 0.0
    arrivals = []
    for o in orders:
        seconds = travel(state.vehicle, node, o.node)
        if not math.isfinite(seconds):
            return Schedule(False, reason='unreachable')
        if seconds < 0:
            raise ValueError('negative travel time')
        clock = max(clock + seconds, o.tw_start, o.release_time)
        if clock > o.tw_end:
            return Schedule(False, reason='time_window')
        arrivals.append(clock)
        clock += o.service_time
        total += seconds
        node = o.node
    return Schedule(True, total, arrivals)


def priority_weight(order):
    """R3 convention: tier 1 HIGH, tier 2 MEDIUM, tier 3 LOW."""
    if order.priority not in (1, 2, 3):
        raise ValueError('priority must be 1, 2 or 3')
    return 4 - order.priority


def adapt_r3_feasibility(engine):
    """Adapt R3 run_feasibility_engine's dictionary to R4's tuple hook.

    Supply a wrapper around the R3 engine if road/shift context is also needed.
    No import from an unmerged branch is required.
    """
    def feasible(vehicle, orders):
        result = engine(vehicle, orders)
        if not isinstance(result, dict) or not isinstance(result.get('feasible'), bool):
            raise ValueError('R3 engine must return a boolean feasible field')
        return result['feasible'], result.get('trace', [])
    return feasible
