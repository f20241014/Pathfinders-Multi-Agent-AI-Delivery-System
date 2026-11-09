"""Exhaustive tiny-instance reference, independent of OR-Tools search."""
from itertools import permutations, product
import math
from src.allocation.cost_model import schedule


def exact_objective(states, orders, travel, drop_penalty=100000):
    """Enumerate assignment, dropping and stop order; intentionally tiny only."""
    if len(orders) > 7:
        raise ValueError('exhaustive checker limited to seven orders')
    best = math.inf
    for owners in product(range(-1, len(states)), repeat=len(orders)):
        penalty = sum(drop_penalty * o.priority for o, v in zip(orders, owners) if v < 0)
        costs = []
        for i, state in enumerate(states):
            assigned = [o for o, owner in zip(orders, owners) if owner == i]
            feasible_costs = []
            for route in permutations(assigned):
                checked = schedule(state, list(route), travel)
                if checked.feasible:
                    feasible_costs.append(checked.travel_seconds)
            costs.append(min(feasible_costs, default=math.inf))
        best = min(best, penalty + sum(costs))
    return best
