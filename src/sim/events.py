"""D11 disruption process: Poisson arrivals of spikes, closures and new orders."""
from typing import Callable, Optional

import numpy as np

from src.sim.models import Event

EVENT_TYPES = ("traffic_spike", "closure", "new_order")
EVENT_PROBS = (0.4, 0.3, 0.3)


class EventGenerator:
    def __init__(
        self,
        env,
        rng: np.random.Generator,
        world,
        event_callback: Callable[[Event], None],
        start_time_s: float = 21600.0,
        min_duration_s: float = 600.0,
        max_duration_s: float = 1800.0,
        min_spike: float = 1.2,
        max_spike: float = 3.0,
    ):
        self.env = env
        self.rng = rng
        self.world = world
        self.event_callback = event_callback
        self.start_time_s = start_time_s
        self.min_duration_s = min_duration_s
        self.max_duration_s = max_duration_s
        self.min_spike = min_spike
        self.max_spike = max_spike
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

    def _emit_road_disruption(self, kind: str) -> None:
        if not self.edges:
            return
        u, v, k = self.edges[int(self.rng.integers(len(self.edges)))]
        t = self.now()
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
