"""D11 disruption process: Poisson arrivals of spikes, closures and new orders.

Closure guard (D11 "closures never disconnect pending destinations"): before a
closure is placed, the road is checked against every vehicle's pending order
nodes. A road whose closure would cut a vehicle off from a destination it can
reach right now is redrawn; after `max_closure_attempts` failed draws the
closure is skipped and logged as `closure_skipped`.
"""
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import numpy as np

from src.sim.models import Event

EVENT_TYPES = ("traffic_spike", "closure", "new_order")
EVENT_PROBS = (0.4, 0.3, 0.3)

# Defaults for the `disruptions:` block of the config (D11).
DISRUPTION_DEFAULTS = {
    "min_duration_s": 600.0,
    "max_duration_s": 1800.0,
    "min_spike": 1.2,
    "max_spike": 3.0,
    "max_closure_attempts": 20,
}

# (source node, pending destination nodes) for each vehicle.
PendingTargets = List[Tuple[object, Iterable[object]]]


def check_disruption_params(
    min_duration_s: float, max_duration_s: float,
    min_spike: float, max_spike: float, max_closure_attempts: int,
) -> None:
    """Raise ValueError for settings the simulator or planners cannot handle."""
    if not 0 < min_duration_s <= max_duration_s:
        raise ValueError(
            f"need 0 < min_duration_s <= max_duration_s, got "
            f"{min_duration_s}, {max_duration_s}"
        )
    # Planners (R2 time-dependent search, R7 D* Lite) assume spikes only slow roads.
    if not 1.0 <= min_spike <= max_spike:
        raise ValueError(f"need 1.0 <= min_spike <= max_spike, got {min_spike}, {max_spike}")
    if int(max_closure_attempts) < 1:
        raise ValueError(f"max_closure_attempts must be >= 1, got {max_closure_attempts}")


class EventGenerator:
    def __init__(
        self,
        env,
        rng: np.random.Generator,
        world,
        event_callback: Callable[[Event], None],
        start_time_s: float = 21600.0,
        min_duration_s: float = DISRUPTION_DEFAULTS["min_duration_s"],
        max_duration_s: float = DISRUPTION_DEFAULTS["max_duration_s"],
        min_spike: float = DISRUPTION_DEFAULTS["min_spike"],
        max_spike: float = DISRUPTION_DEFAULTS["max_spike"],
        max_closure_attempts: int = DISRUPTION_DEFAULTS["max_closure_attempts"],
        pending_targets: Optional[Callable[[], PendingTargets]] = None,
        log_fn: Optional[Callable[[str, float, dict], None]] = None,
    ):
        check_disruption_params(
            min_duration_s, max_duration_s, min_spike, max_spike, max_closure_attempts
        )
        self.env = env
        self.rng = rng
        self.world = world
        self.event_callback = event_callback
        self.start_time_s = start_time_s
        self.min_duration_s = min_duration_s
        self.max_duration_s = max_duration_s
        self.min_spike = min_spike
        self.max_spike = max_spike
        self.max_closure_attempts = int(max_closure_attempts)
        self.pending_targets = pending_targets
        self.log_fn = log_fn
        self.edges = list(world.graph().edges(keys=True))   # cached once
        self._order_counter = 0

    def now(self) -> float:
        return self.start_time_s + self.env.now

    def schedule_disruptions(
        self, rate_per_hour: float, duration_seconds: Optional[float] = None
    ):
        """SimPy process. Exponential gaps with mean 3600 / rate seconds."""
        if rate_per_hour <= 0:
            return
        mean_gap_s = 3600.0 / rate_per_hour
        while True:
            gap = float(self.rng.exponential(mean_gap_s))
            if duration_seconds is not None and self.env.now + gap > duration_seconds:
                return
            yield self.env.timeout(gap)
            idx = int(self.rng.choice(len(EVENT_TYPES), p=EVENT_PROBS))
            event_type = EVENT_TYPES[idx]
            if event_type == "new_order":
                self._emit_new_order()
            else:
                self._emit_road_disruption(event_type)

    # ------------------------------------------------------------------
    # Closure guard
    # ------------------------------------------------------------------
    def closure_disconnects(self, edge, t: float) -> bool:
        """True if closing `edge` at time t cuts a vehicle off from a pending
        destination that it can reach with the roads closed right now."""
        if self.pending_targets is None:
            return False
        targets = [(src, set(dests)) for src, dests in self.pending_targets() if dests]
        if not targets:
            return False
        closed_now = self.world.active_closures(t)
        if edge in closed_now:
            return False                       # already closed: nothing changes
        u, v, k = edge
        closed_after = closed_now | {edge}
        # Fast exact check: if v is still reachable from u, any route through
        # u -> v can detour, so nobody is cut off (covers parallel roads too).
        if self.world.has_path(u, v, closed_after):
            return False
        before: Dict[object, Set] = {}
        after: Dict[object, Set] = {}
        for src, dests in targets:
            if src not in after:
                after[src] = self.world.reachable_from(src, closed_after)
            lost = dests - after[src]
            if not lost:
                continue
            if src not in before:
                before[src] = self.world.reachable_from(src, closed_now)
            if lost & before[src]:
                return True
        return False

    # ------------------------------------------------------------------
    # Emitters
    # ------------------------------------------------------------------
    def _emit_road_disruption(self, kind: str) -> None:
        if not self.edges:
            return
        t = self.now()
        u, v, k = self.edges[int(self.rng.integers(len(self.edges)))]
        if kind == "closure":
            attempts = 1
            while self.closure_disconnects((u, v, k), t):
                if attempts >= self.max_closure_attempts:
                    if self.log_fn is not None:
                        self.log_fn("closure_skipped", t, {"attempts": attempts})
                    return
                u, v, k = self.edges[int(self.rng.integers(len(self.edges)))]
                attempts += 1
        duration = float(self.rng.uniform(self.min_duration_s, self.max_duration_s))
        expiry = t + duration
        if kind == "closure":
            magnitude = None                  # a closure has no multiplier
            self.world.add_disruption(u, v, k, expiry, start_t_seconds=t)
        else:
            magnitude = float(self.rng.uniform(self.min_spike, self.max_spike))
            self.world.add_spike(u, v, k, magnitude, expiry, start_t_seconds=t)
        self.event_callback(Event(t, "disruption", {
            "type": kind,
            "edge": [u, v, k],
            "magnitude": magnitude,
            "duration": duration,
            "expiry": expiry,
        }))

    def _emit_new_order(self) -> None:
        # TODO(R3): create a real Order (node, demand, time window) and hand
        # it to env.add_order(); for now only the arrival is announced.
        self._order_counter += 1
        t = self.now()
        self.event_callback(Event(t, "new_order", {
            "order_id": f"dyn_{self._order_counter}",
            "release_time": t,
        }))
