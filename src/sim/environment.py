import simpy
from typing import List
from src.sim.dataclasses import Vehicle, Event
class DeliverySimEnvironment:
    def __init__(self, mode: str = "independent"):
        self.env = simpy.Environment()
        self.mode = mode  
        self.vehicles: List[Vehicle] = []
        self.events: List[Event] = []
    def vehicle_process(self, vehicle: Vehicle):
        while True:
            if not vehicle.remaining_route:
                yield self.env.timeout(1)
                continue
            next_node = vehicle.remaining_route.pop(0)
            traversal_time = 10.0  
            yield self.env.timeout(traversal_time)
            vehicle.current_node = next_node
            print(f"[{self.env.now:.1f}s] Vehicle {vehicle.id} reached node {vehicle.current_node}")
    def add_vehicle(self, vehicle: Vehicle):
        self.vehicles.append(vehicle)
        self.env.process(self.vehicle_process(vehicle))
    def run(self, until_time: float):
        print(f"Starting simulation in '{self.mode}' mode...")
        self.env.run(until=until_time)
        print("Simulation complete.")
if __name__ == "__main__":
    sim = DeliverySimEnvironment(mode="independent")
    v1 = Vehicle(id="V1", depot_node=100, capacity=50.0, current_node=100, remaining_route=[101, 102, 103])
    sim.add_vehicle(v1)
    sim.run(until_time=60.0)