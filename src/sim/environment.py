import simpy
from typing import List
from src.sim.dataclasses import Vehicle, Event
from src.sim.events import EventGenerator
from src.sim.logger import SimulationLogger

class DeliverySimEnvironment:
    def __init__(self, mode: str = "independent"):
        self.env = simpy.Environment()
        self.mode = mode
        self.vehicles: List[Vehicle] = []
        self.events: List[Event] = []
        self.logger = SimulationLogger()
        self.event_gen = EventGenerator(self.env, self.handle_event)

    def handle_event(self, event: Event):
        self.events.append(event)
        self.logger.log("disruption_event", self.env.now, {
            "type": event.type,
            "target": event.target,
            "magnitude": event.magnitude,
            "duration": event.duration
        })

    def vehicle_process(self, vehicle: Vehicle):
        while True:
            if not vehicle.remaining_route:
                yield self.env.timeout(1)
                continue

            next_node = vehicle.remaining_route.pop(0)
            traversal_time = 10.0
            yield self.env.timeout(traversal_time)
            vehicle.current_node = next_node

            self.logger.log("vehicle_arrival", self.env.now, {
                "vehicle_id": vehicle.id,
                "node": vehicle.current_node,
                "current_load": vehicle.current_load
            })
            print(f"[{self.env.now:.1f}s] Vehicle {vehicle.id} reached node {vehicle.current_node}")

    def add_vehicle(self, vehicle: Vehicle):
        self.vehicles.append(vehicle)
        self.env.process(self.vehicle_process(vehicle))

    def run(self, until_time: float):
        print(f"Starting simulation in '{self.mode}' mode...")
        self.logger.log("sim_start", 0.0, {"mode": self.mode})
        self.env.process(self.event_gen.generate_poisson_events(rate=0.05, total_time=until_time))
        self.env.run(until=until_time)
        self.logger.log("sim_complete", self.env.now, {})
        print("Simulation complete. Log saved to docs/sim_log.jsonl")

if __name__ == "__main__":
    sim = DeliverySimEnvironment(mode="independent")
    v1 = Vehicle(id="V1", depot_node=100, capacity=50.0, current_node=100, remaining_route=[101, 102, 103, 104, 105])
    sim.add_vehicle(v1)
    sim.run(until_time=60.0)