"""Conflict Detection Module: Translates routes to occupancies and sweeps for capacity overloads."""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

Node = str
Edge = Tuple[Node, Node]


@dataclass(frozen=True)
class VehicleRoute:
    vehicle_id: str
    nodes: Sequence[Node]
    start_time: float
    travel_times: Dict[Edge, float]
    priority_weight: float = 1.0
    detour_extra_time: float = 5.0


@dataclass(frozen=True)
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
        """TTC = start of earliest conflict minus current time t_now."""
        return self.overlap_start - t_now


def get_edge_time(times: Dict[Edge, float], u: Node, v: Node) -> float:
    if (u, v) in times:
        duration = float(times[(u, v)])
    else:
        raise ValueError(f"Missing travel time for directed edge {u}->{v}")
    if duration <= 0:
        raise ValueError(f"Travel time for {u}->{v} must be positive")
    return duration


def prepare_occupancies(routes: Iterable[VehicleRoute]) -> List[RoadOccupancy]:
    """Convert vehicle routes into timed edge-occupancy intervals [planned_enter, planned_exit]."""
    occupancies: List[RoadOccupancy] = []
    seen_ids: Set[str] = set()

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
                edge=(u, v),
                entry_time=current_time,
                exit_time=current_time + duration,
            ))
            current_time += duration

    return occupancies


def detect_conflicts(
    occupancies: Iterable[RoadOccupancy],
    edge_capacities: Optional[Dict[Edge, int]] = None,
    delta_t: float = 0.0,
) -> List[Conflict]:
    """Sweeps over entry/exit events to detect capacity overloads on directed edges."""
    if edge_capacities is None:
        edge_capacities = {}

    edge_groups: Dict[Edge, List[RoadOccupancy]] = {}
    for item in occupancies:
        edge_groups.setdefault(item.edge, []).append(item)

    conflicts: List[Conflict] = []

    for edge, users in edge_groups.items():
        k_e = edge_capacities.get(edge, 1)

        # Create sweep-line events: (time, event_type, occupancy)
        events = []
        for u in users:
            events.append((u.entry_time, "ENTRY", u))
            events.append((u.exit_time, "EXIT", u))

        # Sort events by time; ENTRY before EXIT on tie
        events.sort(key=lambda x: (x[0], 0 if x[1] == "ENTRY" else 1))

        active_occupancies: Set[RoadOccupancy] = set()

        for t, event_type, occ in events:
            if event_type == "ENTRY":
                active_occupancies.add(occ)
                if len(active_occupancies) > k_e:
                    active_list = sorted(list(active_occupancies), key=lambda x: x.entry_time)
                    # Check pairwise conflicts among currently active vehicles exceeding capacity
                    for i in range(len(active_list)):
                        for j in range(i + 1, len(active_list)):
                            a, b = active_list[i], active_list[j]
                            if a.vehicle_id == b.vehicle_id:
                                continue

                            start_t = max(a.entry_time, b.entry_time)
                            end_t = min(a.exit_time, b.exit_time)
                            vehicle_set = {a.vehicle_id, b.vehicle_id}

                            if start_t < end_t:
                                if not any(
                                    c.edge == edge and c.vehicles == vehicle_set and c.overlap_start == start_t
                                    for c in conflicts
                                ):
                                    conflicts.append(Conflict(
                                        edge=edge,
                                        vehicles=vehicle_set,
                                        overlap_start=start_t,
                                        overlap_end=end_t,
                                        earliest_arrival=min(a.entry_time, b.entry_time),
                                    ))
            else:
                active_occupancies.discard(occ)

    return sorted(conflicts, key=lambda c: (c.overlap_start, c.edge, sorted(c.vehicles)))


def verify_conflicts_brute_force(
    occupancies: Iterable[RoadOccupancy],
    edge_capacities: Optional[Dict[Edge, int]] = None,
    delta_t: float = 0.0,
) -> List[Conflict]:
    """Capacity-aware brute-force checker used to validate sweep detect_conflicts()."""
    edge_caps = edge_capacities or {}
    items = list(occupancies)
    conflicts: List[Conflict] = []

    edge_groups: Dict[Edge, List[RoadOccupancy]] = {}
    for item in items:
        edge_groups.setdefault(item.edge, []).append(item)

    for edge, users in edge_groups.items():
        k_e = edge_caps.get(edge, 1)

        for i in range(len(users)):
            for j in range(i + 1, len(users)):
                a, b = users[i], users[j]
                if a.vehicle_id == b.vehicle_id:
                    continue

                start = max(a.entry_time, b.entry_time)
                end = min(a.exit_time, b.exit_time)

                if start < end:
                    # Count concurrent vehicles present during this overlap interval
                    concurrent_count = sum(
                        1 for u in users if u.entry_time < end and u.exit_time > start
                    )
                    if concurrent_count > k_e:
                        conflicts.append(Conflict(
                            edge=edge,
                            vehicles={a.vehicle_id, b.vehicle_id},
                            overlap_start=start,
                            overlap_end=end,
                            earliest_arrival=min(a.entry_time, b.entry_time),
                        ))

    # Remove duplicates if any
    unique_conflicts = []
    for c in conflicts:
        if not any(
            uc.edge == c.edge and uc.vehicles == c.vehicles and uc.overlap_start == c.overlap_start
            for uc in unique_conflicts
        ):
            unique_conflicts.append(c)

    return sorted(unique_conflicts, key=lambda c: (c.overlap_start, c.edge, sorted(c.vehicles)))