"""Deterministic, synchronous contract-net allocation; no negotiation messages."""
from dataclasses import dataclass
from time import process_time

from src.allocation.cost_model import schedule, validate


@dataclass
class Bid:
    vehicle_id: str
    cost: float
    orders: list


@dataclass
class AllocationResult:
    vehicle_id: str | None
    bids: list[Bid]
    messages: int
    cpu_seconds: float
    reason: str = ''


def insertion_cost(state, order, travel, now=0, feasibility=None):
    """Cheapest feasible position; negative marginal cost is allowed."""
    baseline = schedule(state, state.orders, travel, now, feasibility)
    if not baseline.feasible:
        return None
    candidates = []
    for pos in range(len(state.orders) + 1):
        orders = state.orders[:pos] + [order] + state.orders[pos:]
        result = schedule(state, orders, travel, now, feasibility)
        if result.feasible:
            candidates.append((result.travel_seconds - baseline.travel_seconds, pos, orders))
    if not candidates:
        return None
    cost, _, orders = min(candidates, key=lambda x: (x[0], x[1]))
    return Bid(state.vehicle.id, cost, orders)


class ContractNet:
    """Stateful awards prevent duplicate allocation across successive calls.

    `emit(kind, payload)` optionally logs individual recipient messages. All are
    allocation messages; phase is announcement, bid, or award. No infeasible bid.
    """

    def __init__(self, travel, feasibility=None, emit=None):
        self.travel = travel
        self.feasibility = feasibility
        self.emit = emit
        self.awarded = set()

    def allocate(self, order, states, now=0):
        start = process_time()
        validate(states, [order])
        if order.id in self.awarded or any(
                order.id == o.id for s in states for o in s.orders):
            raise ValueError('order already assigned')
        messages = 0

        def send(phase, recipient, **extra):
            nonlocal messages
            messages += 1
            if self.emit:
                self.emit('allocation', dict(phase=phase, recipient=recipient,
                                             order_id=order.id, **extra))

        bids = []
        for state in sorted(states, key=lambda s: s.vehicle.id):
            send('announcement', state.vehicle.id)
            bid = insertion_cost(state, order, self.travel, now, self.feasibility)
            if bid is not None:
                bids.append(bid)
                send('bid', 'manager', sender=bid.vehicle_id, cost=bid.cost)
        winner = min(bids, key=lambda b: (b.cost, b.vehicle_id)) if bids else None
        if winner is not None:
            next(s for s in states if s.vehicle.id == winner.vehicle_id).orders = winner.orders
            self.awarded.add(order.id)
            send('award', winner.vehicle_id)
        return AllocationResult(winner.vehicle_id if winner else None, bids, messages,
                                process_time() - start, '' if winner else 'no_feasible_bid')

