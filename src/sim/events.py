# src/sim/events.py
import numpy as np
from typing import Callable, List, Tuple
from src.sim.models import Event

class EventGenerator:
    def __init__(self, env, rng: np.random.Generator, world, event_callback: Callable[[Event], None]):
        self.env = env
        self.rng = rng
        self.world = world
        self.event_callback = event_callback
        
        # Extract edge list from network graph
        self.edges: List[Tuple[int, int]] = list(self.world.graph().edges())

    def generate_poisson_events(self, rate_per_hour: float = 5.0, total_duration_s: float = 14400.0,
                                min_duration_s: float = 600.0, max_duration_s: float = 1800.0):
        if rate_per_hour <= 0:
            return

        rate_per_sec = rate_per_hour / 3600.0
        t_curr = 0.0

        while t_curr < total_duration_s:
            inter_arrival = self.rng.exponential(1.0 / rate_per_sec)
            yield self.env.timeout(inter_arrival)
            t_curr = self.env.now

            # Decision D11 Distribution: 40% Traffic Spike, 30% Closure, 30% New Order
            event_type = self.rng.choice(["traffic_spike", "closure", "new_order"], p=[0.4, 0.3, 0.3])
            
            edge = self.edges[self.rng.integers(0, len(self.edges))]
            target_str = f"{edge[0]},{edge[1]}"

            magnitude = float(np.round(self.rng.uniform(1.2, 3.0), 2))
            duration = float(np.round(self.rng.uniform(min_duration_s, max_duration_s), 2))

            event = Event(
                t=round(t_curr, 2),
                type=event_type,
                target=target_str,
                magnitude=magnitude if event_type != "closure" else 1.0,
                duration=duration
            )

            if event_type in ["traffic_spike", "closure"]:
                self.world.add_disruption(event)
                
            # TODO (Week 3): Guard closures to ensure pending destinations remain connected
            # TODO (Week 3): Dispatch new_order to R3's Order Generator

            self.event_callback(event)