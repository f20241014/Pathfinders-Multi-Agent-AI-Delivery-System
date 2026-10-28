import random
from typing import Callable
from src.sim.dataclasses import Event

class EventGenerator:
    def __init__(self, env, event_callback: Callable[[Event], None]):
        self.env = env
        self.event_callback = event_callback

    def generate_poisson_events(self, rate: float = 0.05, total_time: float = 100.0):
        t_curr = 0.0
        event_id = 0

        while t_curr < total_time:
            inter_arrival = random.expovariate(rate)
            yield self.env.timeout(inter_arrival)

            t_curr = self.env.now
            event_id += 1
            
            event_type = random.choice(["traffic_spike", "closure", "new_order"])
            
            event = Event(
                t=round(t_curr, 2),
                type=event_type,
                target=f"edge_{random.randint(1, 20)}",
                magnitude=round(random.uniform(1.2, 3.0), 2),
                duration=round(random.uniform(10.0, 30.0), 2)
            )

            print(f"[{t_curr:.1f}s] DISRUPTION EVENT #{event_id}: {event.type} on {event.target} (Mag: {event.magnitude}x, Duration: {event.duration}s)")
            self.event_callback(event)