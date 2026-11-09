"""Exact baseline quality and executable SimPy flow, including in-flight events."""
import json
import pytest
from src.allocation.central_vrp import CentralVRP
from src.allocation.quality import exact_objective
from src.allocation.sim_runner import AllocationSimulation
from src.sim.models import Event, Order
from test_allocation_w2 import state, distance
from test_allocation_w4 import world


@pytest.mark.parametrize('capacity', [1, 2, 3])
def test_solver_matches_independent_exhaustive_objective(capacity):
    states = [state('a', capacity), state('b', capacity)]
    orders = [Order(str(i), i, 1, priority=1 + i % 3, service_time=0)
              for i in range(1, 5)]
    result = CentralVRP(distance, 0.1).resolve(states, orders)
    assert result.objective == exact_objective(states, orders, distance)


@pytest.mark.parametrize('mode', ['centralized', 'independent', 'full'])
def test_sim_delivers_dynamic_orders_and_handles_mid_edge_closure(mode, tmp_path):
    config = dict(mode=mode, start_time_s=0, log_path=str(tmp_path / 'sim.jsonl'),
                  solver_time_limit_s=0.05)
    sim = AllocationSimulation(world(), config)
    for name in ('a', 'b'):
        sim.add_vehicle(state(name, 3).vehicle)
    sim.add_order(Order('initial', 2, 1, service_time=2))
    sim.add_order(Order('dynamic', 1, 1, release_time=1, service_time=2))
    sim.add_order(Order('failed', 1, 10, release_time=3))

    def closure():
        yield sim.env.timeout(1)
        sim.world.add_disruption(0, 1, 0, expiry_t_seconds=50)
        sim.handle_event(Event(1, 'closure', {'edge': [0, 1, 0]}))

    sim.env.process(closure())
    sim.run(100)
    assert sim.terminal == {'failed': 'failed', 'dynamic': 'delivered', 'initial': 'delivered'}
    assert sim.n_delivered == 2 and sim.n_failed == 1
    rows = [json.loads(line) for line in (tmp_path / 'sim.jsonl').read_text().splitlines()]
    delivered = [r['payload']['order_id'] for r in rows if r['event'] == 'order_delivered']
    assert len(set(delivered)) == len(delivered) == 2
    assert not any('negotiation' in r['event'] for r in rows)
