"""Trigger Policies Module: Evaluates when conflicts warrant negotiation."""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from src.coordination.conflict import Conflict, VehicleRoute

Edge = Tuple[str, str]


@dataclass
class ConflictTriggerEvent:
    event_type: str
    edge: Edge
    vehicles: Tuple[str, ...]
    trigger_time: float
    overlap_end: float
    ttc: float


class TriggerPolicy:
    """Common interface for coordination triggers matching project plan."""
    def should_negotiate(
        self,
        vehicle: VehicleRoute,
        routes: Dict[str, VehicleRoute],
        t: float,
        conflict: Optional[Conflict] = None,
    ) -> bool:
        raise NotImplementedError


class NeverTrigger(TriggerPolicy):
    """Independent baseline: never negotiates."""
    def should_negotiate(
        self,
        vehicle: VehicleRoute,
        routes: Dict[str, VehicleRoute],
        t: float,
        conflict: Optional[Conflict] = None,
    ) -> bool:
        return False


class AlwaysTrigger(TriggerPolicy):
    """Ablation condition: always negotiates if a conflict exists."""
    def should_negotiate(
        self,
        vehicle: VehicleRoute,
        routes: Dict[str, VehicleRoute],
        t: float,
        conflict: Optional[Conflict] = None,
    ) -> bool:
        return conflict is not None


class ThresholdTrigger(TriggerPolicy):
    """Proposed system: negotiates iff TTC < tau (including negative TTC for ongoing conflicts)."""
    def __init__(self, tau: float, delta_t: float = 0.0):
        self.tau = tau
        self.delta_t = delta_t

    def should_negotiate(
        self,
        vehicle: VehicleRoute,
        routes: Dict[str, VehicleRoute],
        t: float,
        conflict: Optional[Conflict] = None,
    ) -> bool:
        if conflict is None:
            return False
        ttc = conflict.time_to_conflict(t)
        # Negotiate if TTC < tau (ongoing conflicts with TTC < 0 also trigger)
        return ttc < self.tau


def filter_and_trigger_conflicts(
    conflicts: Iterable[Conflict],
    trigger_policy: TriggerPolicy,
    routes_dict: Dict[str, VehicleRoute],
    t_now: float,
) -> List[ConflictTriggerEvent]:
    """Generate negotiation trigger events for conflicts satisfying the policy."""
    events: List[ConflictTriggerEvent] = []
    for c in conflicts:
        ttc = c.time_to_conflict(t_now)
        # Check if any involved vehicle triggers negotiation
        any_triggered = False
        for v_id in c.vehicles:
            if v_id in routes_dict and trigger_policy.should_negotiate(
                routes_dict[v_id], routes_dict, t_now, conflict=c
            ):
                any_triggered = True
                break

        if any_triggered:
            events.append(ConflictTriggerEvent(
                event_type="ROAD_SLOT_NEGOTIATION_TRIGGER",
                edge=c.edge,
                vehicles=tuple(sorted(c.vehicles)),
                trigger_time=t_now,
                overlap_end=c.overlap_end,
                ttc=ttc,
            ))
    return events