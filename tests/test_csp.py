"""R3 Week 3: CSP checked against brute force and python-constraint, AC-3 soundness,
exact sequencing, the bidding filter, and integration with R1 models, R2's matrix and
R4's allocator.
Times are seconds since midnight; T is 06:00.  Run: python -m pytest tests/test_csp.py -q
"""

import itertools
import math
import random

import pytest

from src.kr.csp import AssignmentCSP, eligible_vehicles, find_sequence, set_feasible, solve_batch
from src.kr.ontology import SIM_START_S as T, Order, Vehicle, tw_of
from src.kr.rules import feasible


# ------------------------------------------------------------ helpers (independent of csp.py)
def const_tt(a, b, t):
    return 10.0


def line_tt(a, b, t):
    return 60.0 * abs(a - b)


def euclid_world(seed, n_nodes=60, size=4000, speed=8.0):
    rng = random.Random(seed)
    pts = {i: (rng.random() * size, rng.random() * size) for i in range(n_nodes)}
    return lambda a, b, t: math.dist(pts[a], pts[b]) / speed


def random_instance(seed, n_orders, n_veh, tight=True):
    rng = random.Random(seed)
    vehicles = [Vehicle(f"V{i}", 0, rng.randint(5, 9), shift_end=T + 6000) for i in range(n_veh)]
    orders = []
    for i in range(n_orders):
        s = T + rng.uniform(0, 2500)
        w = rng.uniform(400, 1500) if tight else 5000
        orders.append(
            Order(
                f"O{i}",
                rng.randint(1, 59),
                rng.randint(1, 4),
                rng.randint(1, 3),
                tw_start=s,
                tw_end=s + w,
                service_time=120,
                release_time=T,
            )
        )
    return vehicles, orders, euclid_world(seed)


def brute_set_ok(v, orders, tt, t0=T):
    """Try every permutation (no pruning) - the reference the CSP must agree with."""
    if v.load + sum(o.demand for o in orders) > v.capacity:
        return False
    for perm in itertools.permutations(orders):
        t, node, ok = t0, v.current_node, True
        for o in perm:
            arr = t + tt(node, o.node, t)
            tw = tw_of(o)
            start = max(arr, tw[0] if tw else -math.inf, o.release_time)
            if tw and start > tw[1]:
                ok = False
                break
            t, node = start + o.service_time, o.node
        if ok and t + tt(node, v.depot_node, t) <= v.shift_end:
            return True
    return False


def brute_solutions(vehicles, orders, tt):
    sols = []
    for combo in itertools.product([v.id for v in vehicles], repeat=len(orders)):
        if all(
            brute_set_ok(v, [o for o, c in zip(orders, combo) if c == v.id], tt) for v in vehicles
        ):
            sols.append(dict(zip([o.id for o in orders], combo)))
    return sols


CONFIGS = [
    dict(mrv=False, fc=False, ac3=False, lcv=False),  # plain backtracking
    dict(mrv=True, fc=False, ac3=False, lcv=False),
    dict(mrv=True, fc=True, ac3=False, lcv=False),
    dict(mrv=True, fc=True, ac3=True, lcv=True),
    dict(mrv=True, fc=True, ac3=True, lcv=True, mac=True),
]


# ------------------------------------------------------------ sequencing
@pytest.mark.parametrize("seed", range(40))
def test_find_sequence_matches_permutations(seed):
    vehicles, orders, tt = random_instance(seed, 5, 1)
    v = Vehicle("V", 0, 99, shift_end=T + 6000)
    seq, _ = find_sequence(v, orders, tt)
    assert (seq is not None) == brute_set_ok(v, orders, tt)
    if seq is not None:  # the returned order really works
        assert brute_set_ok(v, seq, tt) and sorted(o.id for o in seq) == sorted(
            o.id for o in orders
        )


# ------------------------------------------------------------ assignment CSP vs brute force
@pytest.mark.parametrize("seed", range(25))
@pytest.mark.parametrize("cfg", CONFIGS, ids=["bt", "mrv", "mrv+fc", "mrv+fc+ac3+lcv", "mac"])
def test_csp_agrees_with_brute_force(seed, cfg):
    vehicles, orders, tt = random_instance(seed, 6, 3)
    sols = brute_solutions(vehicles, orders, tt)
    res = AssignmentCSP(vehicles, orders, tt).solve(**cfg)
    assert res.feasible == bool(sols)
    if res.feasible:
        assert res.assignment in sols


@pytest.mark.parametrize("seed", range(25))
def test_ac3_never_removes_a_value_used_by_a_solution(seed):
    vehicles, orders, tt = random_instance(seed, 6, 3)
    sols = brute_solutions(vehicles, orders, tt)
    csp = AssignmentCSP(vehicles, orders, tt)
    doms, _ = csp.unary_domains()
    nb = csp._neighbours(doms)
    consistent = csp.ac3(doms, nb)
    if sols:
        assert consistent
        for s in sols:
            for oid, vid in s.items():
                assert vid in doms[oid]


def test_ac3_prunes_on_a_hand_made_case():
    """O1 fits only V1; O2 fits V1 or V2 but not with O1 (capacity) -> AC-3 drops V1 from O2."""
    tt = const_tt
    V = [Vehicle("V1", 0, 5), Vehicle("V2", 0, 3)]
    orders = [Order("O1", 1, 4, 1), Order("O2", 2, 2, 1)]
    csp = AssignmentCSP(V, orders, tt)
    doms, _ = csp.unary_domains()
    assert doms == {"O1": ["V1"], "O2": ["V1", "V2"]}
    assert csp.ac3(doms, csp._neighbours(doms))
    assert doms == {"O1": ["V1"], "O2": ["V2"]} and csp.stats.ac3_removed == 1


def test_ac3_detects_infeasibility_before_search():
    tt = const_tt
    V = [Vehicle("V1", 0, 5)]
    orders = [Order("O1", 1, 4, 1), Order("O2", 2, 2, 1)]
    res = solve_batch(V, orders, tt)
    assert not res.feasible and res.stats.nodes == 0


def test_order_nobody_can_serve_is_rejected_with_reason():
    tt = const_tt
    res = solve_batch([Vehicle("V1", 0, 5)], [Order("big", 1, 9, 1)], tt)
    assert not res.feasible and "big" in res.rejected


def test_python_constraint_agrees():
    constraint = pytest.importorskip("constraint")
    for seed in range(15):
        vehicles, orders, tt = random_instance(seed, 5, 3)
        p = constraint.Problem()
        ids = [o.id for o in orders]
        p.addVariables(ids, [v.id for v in vehicles])

        def all_ok(*vals):
            return all(
                brute_set_ok(v, [o for o, c in zip(orders, vals) if c == v.id], tt)
                for v in vehicles
            )

        p.addConstraint(constraint.FunctionConstraint(all_ok), ids)
        assert (p.getSolution() is not None) == AssignmentCSP(vehicles, orders, tt).solve().feasible


def test_mrv_and_pruning_never_visit_more_nodes_than_plain_on_average():
    plain = pruned = 0
    for seed in range(20):
        vehicles, orders, tt = random_instance(seed, 8, 3)
        plain += AssignmentCSP(vehicles, orders, tt).solve(**CONFIGS[0]).stats.nodes
        pruned += AssignmentCSP(vehicles, orders, tt).solve(**CONFIGS[4]).stats.nodes
    assert pruned <= plain


def test_node_limit_reports_instead_of_hanging():
    vehicles, orders, tt = random_instance(3, 9, 3)
    res = AssignmentCSP(vehicles, orders, tt).solve(**CONFIGS[0], node_limit=3)
    assert res.stats.nodes <= 3 and (res.feasible or res.stats.limit_hit)


# ------------------------------------------------------------ bidding filter
def test_eligible_vehicles_and_explanations():
    tt = line_tt
    V = [Vehicle("near", 0, 10), Vehicle("full", 0, 10, load=10), Vehicle("far", 50, 10)]
    o = Order("new", 2, 1, 1, tw_start=T, tw_end=T + 600, service_time=60)
    ok, why = eligible_vehicles(o, V, tt, explain=True)
    assert ok == ["near"]
    assert "KR-1" in why["full"][-1] and "KR-8" in why["far"][-1]


def test_eligible_respects_committed_orders():
    tt = line_tt
    V = [Vehicle("V1", 0, 10)]
    busy = Order("busy", 9, 1, 1, tw_start=T, tw_end=T + 600, service_time=600)
    new = Order("new", 1, 1, 1, tw_start=T + 600, tw_end=T + 700, service_time=60)
    assert eligible_vehicles(new, V, tt)[0] == ["V1"]
    assert eligible_vehicles(new, V, tt, committed={"V1": [busy]})[0] == []


# ------------------------------------------------------------ integration with R1, R2, R4
def test_works_with_r1_models():
    from src.sim.models import Order as SimOrder, Vehicle as SimVehicle

    tt = line_tt
    v = SimVehicle("V1", depot_node=0, capacity=10, current_node=0)
    os_ = [
        SimOrder("a", 3, 4, priority=2, tw_start=21600, tw_end=22000),
        SimOrder("b", 5, 4, priority=1, tw_start=21600, tw_end=23000),
    ]
    assert feasible(v, os_, tt, t_now=21600)[0]
    assert set_feasible(v, os_, tt, 21600)
    assert not set_feasible(v, os_ + [SimOrder("c", 1, 4)], tt, 21600)  # capacity
    assert solve_batch([v], os_, tt, t_now=21600).feasible


def test_r4_contract_net_uses_the_hook():
    from src.allocation.contract_net import ContractNet
    from src.allocation.cost_model import VehicleState
    from src.kr.adapters import r4_feasibility_hook
    from src.sim.models import Order as SimOrder, Vehicle as SimVehicle

    def travel(v, a, b):
        return 60.0 * abs(a - b)

    hook = r4_feasibility_hook(travel)
    states = [VehicleState(SimVehicle("big", 0, 10, 0)), VehicleState(SimVehicle("tiny", 0, 1, 0))]
    res = ContractNet(travel, feasibility=hook).allocate(SimOrder("o", 1, 5), states)
    assert res.vehicle_id == "big" and len(res.bids) == 1


def test_travel_time_from_r2_matrix():
    import networkx as nx
    from src.kr.adapters import travel_time_from_matrix
    from src.search.travel_matrix import TravelTimeMatrix

    G = nx.MultiDiGraph()
    for u, v, w in [(0, 1, 10), (1, 2, 10), (2, 0, 10), (0, 2, 50)]:
        G.add_edge(u, v, free_flow_time=w)
    ttm = TravelTimeMatrix(G, lambda t: (lambda u, v, d: d["free_flow_time"]))
    tt = travel_time_from_matrix(ttm, [0, 1, 2])
    assert tt(0, 2, 100) == 20 and tt(2, 1, 100) == 20 and tt(1, 1, 5) == 0
    v = Vehicle("V", 0, 10)
    assert feasible(v, [Order("a", 2, 1, 1, tw_start=T, tw_end=T + 25, service_time=0)], tt)[0]
    assert not feasible(v, [Order("b", 2, 1, 1, tw_start=T, tw_end=T + 15)], tt)[0]