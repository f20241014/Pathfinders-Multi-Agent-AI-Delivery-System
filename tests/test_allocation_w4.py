"""World forecasts and the simulator-facing event/mode boundary."""
import networkx as nx
import pytest
from src.allocation.runtime import AllocationController
from src.allocation.world_adapter import WorldTravel
from src.sim.models import Order
from src.sim.world import FakeWorld
from test_allocation_w2 import state


def world():
    g = nx.MultiDiGraph()
    for u, v in [(0, 1), (1, 2), (0, 2), (2, 0), (1, 0), (2, 1)]:
        g.add_edge(u, v, free_flow_time=10 if (u, v) == (0, 2) else 2,
                   highway='primary')
    return FakeWorld(g)


def test_prediction_snapshot_closure_and_restrictions():
    w = world()
    v = state().vehicle
    assert WorldTravel(w, 0)(v, 0, 2) == 4
    w.add_disruption(0, 1, 0, 100)
    assert WorldTravel(w, 0)(v, 0, 2) == 10
    v.allowed_road_classes = ['residential']
    assert WorldTravel(w, 0)(v, 0, 2) == float('inf')


@pytest.mark.parametrize('mode', ['centralized', 'independent', 'full'])
def test_dynamic_orders_no_double_assignment_and_common_failures(mode):
    rows = []
    c = AllocationController(world(), [state('a', 1), state('b', 1)], mode,
                             lambda k, t, p: rows.append((k, p)), time_limit_s=0.05)
    c.event(0, Order('one', 1, 1, service_time=0))
    c.event(1, Order('two', 2, 1, service_time=0))
    assert sorted(o.id for s in c.states for o in s.orders) == ['one', 'two']
    c.event(2, Order('too_big', 1, 100))
    assert 'too_big' in c.failed
    with pytest.raises(ValueError, match='duplicate'):
        c.event(3, Order('one', 1, 1))
    assert not any('negotiation' in kind for kind, _ in rows)


def test_enroute_state_is_next_node_and_active_service_reserves_load():
    c = AllocationController(world(), [state('a', 2)], 'centralized', time_limit_s=0.05)
    c.states[0].vehicle.current_edge = (0, 1, 0)
    c.busy['a'] = (1, 20, 1)
    c.event(5, Order('later', 2, 1, tw_start=22, tw_end=22, service_time=0))
    assert [o.id for o in c.states[0].orders] == ['later']
    assert c.states[0].vehicle.current_node == 0  # snapshot did not teleport live vehicle
    assert c.snapshots()[0].vehicle.load == 1
