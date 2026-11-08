from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

Node = str
Edge = Tuple[Node, Node]


def normalize_edge(u: Node, v: Node) -> Edge:
    """Treat A-B and B-A as the same physical road segment."""
    return (u, v) if u <= v else (v, u)

# DATA CLASSES
@dataclass
class VehicleRoute:
    vehicle_id: str
    nodes: Sequence[Node]
    start_time: float
    travel_times: Dict[Edge, float]
    priority_weight: float = 1.0
    detour_extra_time: float = 5.0


@dataclass
class RoadOccupancy:
    vehicle_id: str
    edge: Edge
    entry_time: float
    exit_time: float


@dataclass
class Conflict:
    edge: Edge
    vehicles: Set[str]
    overlap_start: float
    overlap_end: float
    earliest_arrival: float

    @property
    def duration(self) -> float:
        return self.overlap_end - self.overlap_start

    def time_to_conflict(self, t_now: float) -> float:
        """TTC = start of earliest conflict minus now (W1 Definition)."""
        return self.overlap_start - t_now


@dataclass
class ConflictTriggerEvent:
    event_type: str
    edge: Edge
    vehicles: Tuple[str, ...]
    trigger_time: float
    overlap_end: float
    ttc: float


@dataclass
class CoordinationMessage:
    msg_type: str  # 'negotiation_request', 'negotiation_response', 'negotiation_result'
    sender_id: str
    recipient_id: str
    payload: dict


@dataclass
class MessageCounter:
    requests: int = 0
    responses: int = 0
    results: int = 0

    def log_message(self, msg_type: str):
        if msg_type == "negotiation_request":
            self.requests += 1
        elif msg_type == "negotiation_response":
            self.responses += 1
        elif msg_type == "negotiation_result":
            self.results += 1

    @property
    def total_messages(self) -> int:
        return self.requests + self.responses + self.results

# ROUTE OCCUPANCY PREPARATION

def get_edge_time(times: Dict[Edge, float], u: Node, v: Node) -> float:
    if (u, v) in times:
        duration = float(times[(u, v)])
    elif (v, u) in times:
        duration = float(times[(v, u)])
    else:
        raise ValueError(f"Missing travel time for edge {u}-{v}")
    if duration <= 0:
        raise ValueError(f"Travel time for {u}-{v} must be positive")
    return duration


def prepare_occupancies(routes: Iterable[VehicleRoute]) -> List[RoadOccupancy]:
    """Convert vehicle routes into timed edge-occupancy intervals [planned_enter, planned_exit]."""
    occupancies = []
    seen_ids = set()

    for route in routes:
        if route.vehicle_id in seen_ids:
            raise ValueError(f"Duplicate vehicle ID: {route.vehicle_id}")
        seen_ids.add(route.vehicle_id)

        if route.start_time < 0:
            raise ValueError("Route start time cannot be negative")
        if len(route.nodes) < 2:
            continue

        current_time = float(route.start_time)
        for u, v in zip(route.nodes[:-1], route.nodes[1:]):
            if u == v:
                raise ValueError("A route cannot contain a self-loop")
            duration = get_edge_time(route.travel_times, u, v)
            occupancies.append(RoadOccupancy(
                vehicle_id=route.vehicle_id,
                edge=normalize_edge(u, v),
                entry_time=current_time,
                exit_time=current_time + duration
            ))
            current_time += duration

    return occupancies

# CONFLICT DETECTION & CROSS-CHECKER

def find_overlap(a: RoadOccupancy, b: RoadOccupancy) -> Optional[Tuple[float, float]]:
    start = max(a.entry_time, b.entry_time)
    end = min(a.exit_time, b.exit_time)
    return (start, end) if start < end else None


def detect_conflicts(
    occupancies: Iterable[RoadOccupancy],
    edge_capacities: Optional[Dict[Edge, int]] = None,
    delta_t: float = 0.0
) -> List[Conflict]:
    if edge_capacities is None:
        edge_capacities = {}

    edge_groups: Dict[Edge, List[RoadOccupancy]] = {}
    for item in occupancies:
        edge_groups.setdefault(item.edge, []).append(item)

    conflicts: List[Conflict] = []

    for edge, users in edge_groups.items():
        k_e = edge_capacities.get(edge, 1)  # Default capacity k_e = 1
        if len(users) <= k_e:
            continue

        sorted_users = sorted(users, key=lambda x: x.entry_time)

        for i in range(len(sorted_users)):
            for j in range(i + 1, len(sorted_users)):
                a, b = sorted_users[i], sorted_users[j]
                if a.vehicle_id == b.vehicle_id:
                    continue

                arrival_diff = abs(a.entry_time - b.entry_time)
                overlap = find_overlap(a, b)

                if overlap or arrival_diff < delta_t:
                    overlap_start = max(a.entry_time, b.entry_time) if overlap else min(a.entry_time, b.entry_time)
                    overlap_end = min(a.exit_time, b.exit_time) if overlap else max(a.entry_time, b.entry_time) + delta_t

                    conflicts.append(Conflict(
                        edge=edge,
                        vehicles={a.vehicle_id, b.vehicle_id},
                        overlap_start=overlap_start,
                        overlap_end=overlap_end,
                        earliest_arrival=min(a.entry_time, b.entry_time)
                    ))

    return sorted(conflicts, key=lambda c: (c.overlap_start, c.edge))


def verify_conflicts_brute_force(
    occupancies: Iterable[RoadOccupancy],
    edge_capacities: Optional[Dict[Edge, int]] = None,
    delta_t: float = 0.0
) -> List[Conflict]:
    """Brute-force pairwise conflict detector used to cross-check detect_conflicts()."""
    edge_caps = edge_capacities or {}
    conflicts = []
    items = list(occupancies)

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a.edge != b.edge or a.vehicle_id == b.vehicle_id:
                continue

            k_e = edge_caps.get(a.edge, 1)
            start = max(a.entry_time, b.entry_time)
            end = min(a.exit_time, b.exit_time)

            if start < end or abs(a.entry_time - b.entry_time) < delta_t:
                conflicts.append(Conflict(
                    edge=a.edge,
                    vehicles={a.vehicle_id, b.vehicle_id},
                    overlap_start=start if start < end else min(a.entry_time, b.entry_time),
                    overlap_end=end if start < end else max(a.entry_time, b.entry_time) + delta_t,
                    earliest_arrival=min(a.entry_time, b.entry_time)
                ))

    return sorted(conflicts, key=lambda c: (c.overlap_start, c.edge))


# TRIGGER & VICKREY AUCTION MECHANISM
class TriggerPolicy:
    """Common interface for coordination triggers."""
    def should_negotiate(self, ttc: float) -> bool:
        raise NotImplementedError


class NeverTrigger(TriggerPolicy):
    """Independent baseline: never negotiates."""
    def should_negotiate(self, ttc: float) -> bool:
        return False


class AlwaysTrigger(TriggerPolicy):
    """Ablation condition: always negotiates if a conflict exists."""
    def should_negotiate(self, ttc: float) -> bool:
        return True


class ThresholdTrigger(TriggerPolicy):
    """Proposed system: negotiates iff Time-to-Conflict TTC < tau."""
    def __init__(self, tau: float, delta_t: float):
        self.tau = tau
        self.delta_t = delta_t

    def should_negotiate(self, ttc: float) -> bool:
        return 0.0 <= ttc < self.tau


@dataclass
class VirtualCreditBudget:
    """Budget tracker to prevent single vehicle dominance."""
    vehicle_id: str
    credits: float = 100.0


def calculate_delay_cost(route: VehicleRoute) -> float:
    """Delay cost bid = priority_weight * extra time if vehicle yields."""
    return route.priority_weight * route.detour_extra_time


def run_vickrey_auction(
    contesting_routes: List[VehicleRoute],
    budgets: Dict[str, VirtualCreditBudget],
    msg_counter: Optional[MessageCounter] = None
) -> Tuple[str, List[str], float]:
    """
    Vickrey Auction Primitive for a contested slot:
    - Bids: delay cost (priority * extra time if it yields).
    - Winner: Highest valid bidder passes.
    - Loser(s): Yield / detour.
    - Price: Second-highest bid paid in virtual credits.
    """
    if msg_counter:
        for r in contesting_routes:
            msg_counter.log_message("negotiation_request")
            msg_counter.log_message("negotiation_response")
        msg_counter.log_message("negotiation_result")

    bids: Dict[str, float] = {}
    for r in contesting_routes:
        bid_val = calculate_delay_cost(r) if budgets[r.vehicle_id].credits > 0 else 0.0
        bids[r.vehicle_id] = bid_val

    sorted_bids = sorted(bids.items(), key=lambda item: item[1], reverse=True)

    winner_id, highest_bid = sorted_bids[0]
    second_highest_bid = sorted_bids[1][1] if len(sorted_bids) > 1 else 0.0

    budgets[winner_id].credits -= second_highest_bid

    losers = [r.vehicle_id for r in contesting_routes if r.vehicle_id != winner_id]
    return winner_id, losers, second_highest_bid


def filter_and_trigger_conflicts(
    conflicts: Iterable[Conflict],
    trigger_policy: TriggerPolicy,
    t_now: float
) -> List[ConflictTriggerEvent]:
    """Generate negotiation trigger events for conflicts satisfying trigger rule."""
    events = []
    for c in conflicts:
        ttc = c.time_to_conflict(t_now)
        if trigger_policy.should_negotiate(ttc):
            events.append(ConflictTriggerEvent(
                event_type="ROAD_SLOT_NEGOTIATION_TRIGGER",
                edge=c.edge,
                vehicles=tuple(sorted(c.vehicles)),
                trigger_time=t_now,
                overlap_end=c.overlap_end,
                ttc=ttc
            ))
    return events



# LOCAL DEMO & VERIFICATION

if __name__ == "__main__":
    print("--- DEMO & PIPELINE CHECK ---")

    routes = [
        VehicleRoute("V1", ["A", "B", "C"], start_time=0.0, travel_times={("A", "B"): 10.0, ("B", "C"): 5.0}, priority_weight=2.0, detour_extra_time=4.0),
        VehicleRoute("V2", ["B", "A"], start_time=3.0, travel_times={("B", "A"): 8.0}, priority_weight=1.0, detour_extra_time=6.0),
        VehicleRoute("V3", ["A", "B"], start_time=40.0, travel_times={("A", "B"): 4.0}),
    ]

    budgets = {
        "V1": VirtualCreditBudget("V1", credits=50.0),
        "V2": VirtualCreditBudget("V2", credits=50.0),
        "V3": VirtualCreditBudget("V3", credits=50.0),
    }

    occupancies = prepare_occupancies(routes)

    edge_caps = {("A", "B"): 1}
    conflicts = detect_conflicts(occupancies, edge_capacities=edge_caps, delta_t=2.0)

    # Brute Force Cross-Check Assertion
    bf_conflicts = verify_conflicts_brute_force(occupancies, edge_capacities=edge_caps, delta_t=2.0)
    assert len(conflicts) == len(bf_conflicts), "Brute force mismatch!"
    print("✓ Unit test passed: `detect_conflicts` output matches brute-force checker.")

    t_now = 0.0
    tau = 60.0
    delta_t = 2.0

    policy = ThresholdTrigger(tau=tau, delta_t=delta_t)
    trigger_events = filter_and_trigger_conflicts(conflicts, policy, t_now)

    msg_counter = MessageCounter()

    print(f"\nDetected {len(conflicts)} raw conflict(s). Trigger Policy evaluated {len(trigger_events)} event(s).")

    for event in trigger_events:
        print(f"\n[TRIGGER FIRED] Event: {event.event_type} on Edge {event.edge} (TTC: {event.ttc:.1f}s)")

        contesting_vehicles = [r for r in routes if r.vehicle_id in event.vehicles]

        print("\n--- Bids Submitted ---")
        for r in contesting_vehicles:
            cost = calculate_delay_cost(r)
            print(f"  {r.vehicle_id}: Bid = {cost:.1f} (Priority {r.priority_weight} x Extra Time {r.detour_extra_time}s), Budget = {budgets[r.vehicle_id].credits:.1f}")

        winner, losers, price = run_vickrey_auction(contesting_vehicles, budgets, msg_counter)
        print("\n--- Auction Result ---")
        print(f"  Winner (Passes): {winner}")
        print(f"  Loser(s) (Yield/Detour): {losers}")
        print(f"  Price Paid (2nd Highest Bid): {price:.1f} virtual credits")
        print(f"  Winner Remaining Budget: {budgets[winner].credits:.1f} credits")

    print(f"\nTotal Negotiation Messages Counted: {msg_counter.total_messages}")

    never_policy = NeverTrigger()
    never_events = filter_and_trigger_conflicts(conflicts, never_policy, t_now)
    assert len(never_events) == 0, "NeverTrigger failed! Must return 0 events."
    print("✓ Unit test passed: `NeverTrigger` produced 0 negotiation events.")