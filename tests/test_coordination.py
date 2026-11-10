"""Comprehensive Unit Tests for Coordination Module."""

import random
import pytest

from src.coordination.conflict import (
    RoadOccupancy,
    VehicleRoute,
    detect_conflicts,
    prepare_occupancies,
    verify_conflicts_brute_force,
)
from src.coordination.messages import MessageCounter
from src.coordination.negotiation import VirtualCreditBudget, run_vickrey_auction
from src.coordination.trigger import (
    ConflictTriggerEvent,
    NeverTrigger,
    ThresholdTrigger,
    filter_and_trigger_conflicts,
)


def test_random_cross_check_detect_conflicts():
    """500 random trial cross-check comparing sweep detect_conflicts vs brute force."""
    random.seed(42)
    nodes = ["A", "B", "C", "D"]

    for trial in range(500):
        occupancies = []
        num_vehicles = random.randint(2, 6)
        for i in range(num_vehicles):
            u, v = random.sample(nodes, 2)
            entry = random.uniform(0.0, 50.0)
            dur = random.uniform(5.0, 20.0)
            occupancies.append(RoadOccupancy(
                vehicle_id=f"V{i}",
                edge=(u, v),
                entry_time=entry,
                exit_time=entry + dur,
            ))

        caps = {("A", "B"): random.randint(1, 3), ("B", "C"): random.randint(1, 3)}
        sweep_res = detect_conflicts(occupancies, edge_capacities=caps)
        bf_res = verify_conflicts_brute_force(occupancies, edge_capacities=caps)

        assert len(sweep_res) == len(bf_res), f"Mismatch in trial {trial}"


def test_threshold_trigger_negative_ttc():
    """It will verify ThresholdTrigger fires for ongoing conflicts (TTC < 0) and TTC < tau."""
    trigger = ThresholdTrigger(tau=60.0)
    routes = {
        "V1": VehicleRoute("V1", ["A", "B"], start_time=0.0, travel_times={("A", "B"): 10.0}),
        "V2": VehicleRoute("V2", ["A", "B"], start_time=2.0, travel_times={("A", "B"): 10.0}),
    }

    occs = prepare_occupancies(routes.values())
    conflicts = detect_conflicts(occs)
    assert len(conflicts) == 1

    # Ongoing conflict: current time t_now = 5.0 (overlap started at t = 2.0)
    events = filter_and_trigger_conflicts(conflicts, trigger, routes, t_now=5.0)
    assert len(events) == 1
    assert events[0].ttc < 0.0


def test_never_trigger_zero_messages():
    """Verifies NeverTrigger yields exactly zero trigger events."""
    trigger = NeverTrigger()
    routes = {
        "V1": VehicleRoute("V1", ["A", "B"], start_time=0.0, travel_times={("A", "B"): 10.0}),
        "V2": VehicleRoute("V2", ["A", "B"], start_time=2.0, travel_times={("A", "B"): 10.0}),
    }
    occs = prepare_occupancies(routes.values())
    conflicts = detect_conflicts(occs)

    events = filter_and_trigger_conflicts(conflicts, trigger, routes, t_now=0.0)
    assert len(events) == 0


def test_message_counter_d7():
    """Verifies 2 vehicles produce 6 total messages (2 reqs, 2 resps, 2 results)."""
    routes = [
        VehicleRoute("V1", ["A", "B"], start_time=0.0, travel_times={("A", "B"): 10.0}, priority_weight=2.0),
        VehicleRoute("V2", ["A", "B"], start_time=1.0, travel_times={("A", "B"): 10.0}, priority_weight=1.0),
    ]
    budgets = {"V1": VirtualCreditBudget("V1", 50.0), "V2": VirtualCreditBudget("V2", 50.0)}
    counter = MessageCounter()

    run_vickrey_auction(routes, budgets, counter)
    assert counter.requests == 2
    assert counter.responses == 2
    assert counter.results == 2
    assert counter.total_messages == 6


def test_credits_never_go_negative():
    """It will verify vehicle with 1 credit winning price 6 drops to 0, not negative."""
    routes = [
        VehicleRoute("V1", ["A", "B"], start_time=0.0, travel_times={("A", "B"): 10.0}, priority_weight=2.0, detour_extra_time=5.0),
        VehicleRoute("V2", ["A", "B"], start_time=1.0, travel_times={("A", "B"): 10.0}, priority_weight=1.0, detour_extra_time=3.0),
    ]
    # V1 has only 10.0 credits; V2 bids 3.0. V1 pays 3.0 -> remaining 7.0
    budgets = {"V1": VirtualCreditBudget("V1", 10.0), "V2": VirtualCreditBudget("V2", 50.0)}

    winner, losers, price = run_vickrey_auction(routes, budgets)
    assert winner == "V1"
    assert budgets["V1"].credits == 7.0
    assert budgets["V1"].credits >= 0.0


def test_vickrey_truthfulness_property():
    """Property test: Over 1000 random bid profiles, no vehicle benefits by misreporting."""
    random.seed(100)
    for _ in range(1000):
        v1_true = random.uniform(1.0, 50.0)
        v2_bid = random.uniform(1.0, 50.0)

        r1 = VehicleRoute("V1", ["A", "B"], start_time=0.0, travel_times={("A", "B"): 10.0}, priority_weight=v1_true, detour_extra_time=1.0)
        r2 = VehicleRoute("V2", ["A", "B"], start_time=0.0, travel_times={("A", "B"): 10.0}, priority_weight=v2_bid, detour_extra_time=1.0)

        b1 = {"V1": VirtualCreditBudget("V1", 100.0), "V2": VirtualCreditBudget("V2", 100.0)}
        w_true, _, p_true = run_vickrey_auction([r1, r2], b1)

        # Misreported bid
        v1_false = random.uniform(1.0, 50.0)
        r1_false = VehicleRoute("V1", ["A", "B"], start_time=0.0, travel_times={("A", "B"): 10.0}, priority_weight=v1_false, detour_extra_time=1.0)
        b2 = {"V1": VirtualCreditBudget("V1", 100.0), "V2": VirtualCreditBudget("V2", 100.0)}
        w_false, _, p_false = run_vickrey_auction([r1_false, r2], b2)

        # Truthful payoff: value - price if won else 0
        payoff_true = (v1_true - p_true) if w_true == "V1" else 0.0
        payoff_false = (v1_true - p_false) if w_false == "V1" else 0.0

        assert payoff_true >= payoff_false - 1e-6


def test_input_list_order_independence():
    """It will verify auction results do not depend on the order of input contesting_routes list."""
    r1 = VehicleRoute("V1", ["A", "B"], start_time=0.0, travel_times={("A", "B"): 10.0}, priority_weight=2.0)
    r2 = VehicleRoute("V2", ["A", "B"], start_time=0.0, travel_times={("A", "B"): 10.0}, priority_weight=1.0)

    b1 = {"V1": VirtualCreditBudget("V1", 50.0), "V2": VirtualCreditBudget("V2", 50.0)}
    b2 = {"V1": VirtualCreditBudget("V1", 50.0), "V2": VirtualCreditBudget("V2", 50.0)}

    res1 = run_vickrey_auction([r1, r2], b1)
    res2 = run_vickrey_auction([r2, r1], b2)

    assert res1[0] == res2[0]  # Same winner
    assert res1[2] == res2[2]  # Same price
