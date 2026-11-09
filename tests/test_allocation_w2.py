"""Insertion is checked against hand-calculated route cost and feasibility."""
import pytest

from src.allocation.cost_model import VehicleState
from src.allocation.contract_net import ContractNet, insertion_cost
from src.sim.models import Order, Vehicle


def state(name='v', capacity=10, orders=None):
    return VehicleState(Vehicle(name, 0, capacity, 0), orders or [])


def distance(v, a, b):
    return abs(a - b)


def test_best_insertion_and_no_mutation():
    s = state(orders=[Order('old', 10, 1, service_time=0)])
    bid = insertion_cost(s, Order('new', 3, 1, service_time=0), distance)
    assert bid.cost == 0
    assert [o.id for o in bid.orders] == ['new', 'old']
    assert [o.id for o in s.orders] == ['old']


def test_capacity_windows_and_r3_filter():
    assert insertion_cost(state(capacity=0), Order('a', 1, 1), distance) is None
    assert insertion_cost(state(), Order('a', 100, 1, tw_end=10), distance) is None
    assert insertion_cost(state(), Order('a', 1, 1), distance,
                          feasibility=lambda v, os: (False, 'rule')) is None


def test_messages_tie_and_duplicate_award():
    messages = []
    cnp = ContractNet(distance, emit=lambda k, p: messages.append((k, p)))
    states = [state('b'), state('a')]
    result = cnp.allocate(Order('a', 3, 1), states)
    assert result.vehicle_id == 'a'
    assert result.messages == len(messages) == 2 + 2 + 1
    assert all(kind == 'allocation' for kind, _ in messages)
    with pytest.raises(ValueError, match='already assigned'):
        cnp.allocate(Order('a', 3, 1), states)


def test_no_award_and_unreachable():
    cnp = ContractNet(lambda *args: float('inf'))
    result = cnp.allocate(Order('a', 3, 1), [state('a'), state('b')])
    assert result.vehicle_id is None and result.messages == 2
    assert not cnp.awarded
