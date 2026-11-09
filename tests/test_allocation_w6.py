"""Hardening: invalid inputs, fractional loads, custom rules and terminal audit."""
import pytest
from src.allocation.central_vrp import CentralVRP
from src.allocation.contract_net import ContractNet
from src.allocation.cost_model import schedule
from src.allocation.sim_runner import AllocationSimulation
from src.sim.models import Order
from test_allocation_w2 import state, distance
from test_allocation_w4 import world


@pytest.mark.parametrize('bad', [float('nan'), -1])
def test_bad_load_rejected(bad):
    s = state()
    s.vehicle.load = bad
    with pytest.raises(ValueError):
        CentralVRP(distance, 0.02).resolve([s], [Order('o', 1, 1)])


def test_fractional_residual_load_never_overflows():
    s = state(capacity=1.5)
    s.vehicle.load = 0.5
    orders = [Order('a', 1, 0.6, service_time=0), Order('b', 2, 0.6, service_time=0)]
    result = CentralVRP(distance, 0.03).resolve([s], orders)
    assert len(result.failed) == 1
    assert schedule(s, result.routes['v'], distance).feasible


def test_custom_rules_reject_solver_routes_with_explicit_failure():
    result = CentralVRP(distance, 0.02, feasibility=lambda v, os: (False, 'rule')).resolve(
        [state()], [Order('o', 1, 1)])
    assert result.failed == ['o'] and result.routes == {'v': []}


def test_window_changes_and_unknown_mode():
    with pytest.raises(ValueError):
        ContractNet(distance).allocate(Order('x', 1, -1), [state()])
    result = CentralVRP(distance, 0.02).resolve(
        [state()], [Order('expired', 1, 0, tw_end=1)], now=10)
    assert result.failed == ['expired']


def test_horizon_and_no_vehicle_failure(tmp_path):
    sim = AllocationSimulation(world(), dict(mode='independent', start_time_s=0,
                                             log_path=str(tmp_path/'log.jsonl')))
    sim.add_order(Order('none', 1, 1))
    sim.add_order(Order('future', 1, 1, release_time=1000))
    sim.run(10)
    assert sim.terminal == {'none': 'failed', 'future': 'failed'}
    assert sim.n_failed == 2
