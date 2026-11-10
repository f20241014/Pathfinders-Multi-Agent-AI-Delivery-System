"""Coordination Module: Conflict Detection, Triggers, and Vickrey Auctions."""

from src.coordination.conflict import (
    Conflict,
    RoadOccupancy,
    VehicleRoute,
    detect_conflicts,
    prepare_occupancies,
    verify_conflicts_brute_force,
)
from src.coordination.messages import CoordinationMessage, MessageCounter
from src.coordination.negotiation import (
    VirtualCreditBudget,
    calculate_delay_cost,
    run_vickrey_auction,
)
from src.coordination.trigger import (
    AlwaysTrigger,
    ConflictTriggerEvent,
    NeverTrigger,
    ThresholdTrigger,
    TriggerPolicy,
    filter_and_trigger_conflicts,
)

__all__ = [
    "VehicleRoute",
    "RoadOccupancy",
    "Conflict",
    "ConflictTriggerEvent",
    "CoordinationMessage",
    "MessageCounter",
    "VirtualCreditBudget",
    "TriggerPolicy",
    "NeverTrigger",
    "AlwaysTrigger",
    "ThresholdTrigger",
    "prepare_occupancies",
    "detect_conflicts",
    "verify_conflicts_brute_force",
    "calculate_delay_cost",
    "run_vickrey_auction",
    "filter_and_trigger_conflicts",
]