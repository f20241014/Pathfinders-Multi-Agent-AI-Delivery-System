from typing import Callable
import numpy as np
from src.sim.models import Event


class EventGenerator:
    def __init__(
        self,
        env,
        rng: np.random.Generator,
        world,
        event_callback: Callable[[Event], None],
        start_time_s: float = 21600.0,
    ):
        self.env = env
        self.rng = rng
        self.world = world
        self.event_callback = event_callback
        self.start_time_s = start_time_s

    def schedule_disruptions(
        self, rate_per_hour: float, duration_seconds: float
    ):
        rate_per_sec = rate_per_hour / 3600.0
        while True:
            interval = self.rng.exponential(1.0 / rate_per_sec)
            yield self.env.timeout(interval)
            abs_t = self.start_time_s + self.env.now
            edges = list(self.world.graph.edges(keys=True))
            if edges:
                idx = self.rng.integers(0, len(edges))
                u, v, k = edges[idx]
                expiry = abs_t + 600.0
                self.world.add_disruption(u, v, k, expiry)
                event = Event(
                    t=abs_t,
                    event_type="disruption",
                    payload={"edge": (u, v, k), "expiry": expiry},
                )
                self.event_callback(event)

    def schedule_new_orders(self, rate_per_hour: float):
        # TODO(R3): dynamic new_order dispatching will be
        # handled by R3 order generator
        rate_per_sec = rate_per_hour / 3600.0
        while True:
            interval = self.rng.exponential(1.0 / rate_per_sec)
            yield self.env.timeout(interval)
            abs_t = self.start_time_s + self.env.now
            event = Event(
                t=abs_t,
                event_type="new_order",
                payload={"order_id": f"dyn_{int(abs_t)}"},
            )
            self.event_callback(event)
