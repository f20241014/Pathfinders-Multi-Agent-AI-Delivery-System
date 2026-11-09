"""Cross-role conventions discovered during the repository audit."""
import pytest
from src.allocation.central_vrp import CentralVRP
from src.allocation.contract_net import ContractNet
from src.allocation.cost_model import adapt_r3_feasibility, priority_weight
from src.sim.models import Order
from test_allocation_w2 import state, distance


def test_priority_one_is_highest():
    assert [priority_weight(Order(str(i), i, 1, priority=i)) for i in (1, 2, 3)] == [3, 2, 1]
    orders = [Order('low', 1, 1, priority=3), Order('high', 2, 1, priority=1)]
    result = CentralVRP(distance, 0.05).resolve([state(capacity=1)], orders)
    assert [o.id for o in result.routes['v']] == ['high']
    assert result.failed == ['low']


def test_r3_dictionary_result_can_reject_and_explain():
    adapter = adapt_r3_feasibility(lambda v, os: {'feasible': False, 'trace': ['rejected']})
    assert adapter(state().vehicle, []) == (False, ['rejected'])
    result = ContractNet(distance, feasibility=adapter).allocate(Order('o', 1, 1), [state()])
    assert result.vehicle_id is None
    assert CentralVRP(distance, 0.05, feasibility=adapter).resolve(
        [state()], [Order('o', 1, 1)]).failed == ['o']
    with pytest.raises(ValueError, match='boolean feasible'):
        adapt_r3_feasibility(lambda v, os: {'feasible': 'false'})(state().vehicle, [])
