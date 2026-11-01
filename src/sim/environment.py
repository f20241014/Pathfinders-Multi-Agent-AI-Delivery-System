# src/sim/environment.py
import simpy
import numpy as np
import logging
from typing import List, Dict, Callable
from src.sim.models import Vehicle, Order, Event
from src.sim.events import EventGenerator
from src.sim.logger import SimulationLogger
from src.sim.world import World

logger = logging.getLogger(__name__)

class DeliverySimEnvironment:
    def __init__(self, world: World, config: dict):
        self.env = simpy.Environment()
        self.world = world
        self.config = config
        
        self.run_id = config.get("run_id", "default")
        self.mode = config.get("mode", "independent")
        self.seed = config.get("seed", 42)
        self.scenario = config.get("scenario", "default")
        self.rate = config.get("disruption_rate_per_hour", 5.0)
        self.start_time_s = config.get("start_time_s", 21600.0)  # Default 06:00 AM

        self.rng = np.random.default_rng(self.seed)
        self.logger = SimulationLogger(run_id=self.run_id, output_path=config.get("log_path"))
        self.subscribers: List[Callable[[Event], None]] = []

        self.vehicles: Dict[str, Vehicle] = {}
        self.orders: Dict[str, Order] = {}
        
        self.event_gen = EventGenerator(self.env, self.rng, self.world, self.handle_event)

    def subscribe(self, callback: Callable[[Event], None]):
        self.subscribers.append(callback)

    def handle_event(self, event: Event):
        self.logger.log(
            self.run_id, self.mode, self.seed, self.scenario, self.rate,
            self.env.now, "env", "disruption",
            {"type": event.type, "target": event.target, "magnitude": event.magnitude, "duration": event.duration}
        )
        for sub in self.subscribers:
            sub(event)

    def vehicle_process(self, vehicle: Vehicle, stops: List[Order]):
        stops_by_node = {order.node: order for order in stops}

        while vehicle.remaining_route:
            next_node = vehicle.remaining_route[0]
            current_node = vehicle.current_node

            if current_node == next_node:
                vehicle.remaining_route.pop(0)
                continue

            abs_time = self.start_time_s + self.env.now
            edge_cost = self.world.edge_time(current_node, next_node, abs_time)

            if edge_cost == float("inf"):
                self.logger.log(
                    self.run_id, self.mode, self.seed, self.scenario, self.rate,
                    self.env.now, vehicle.id, "blocked_wait", {"edge": [current_node, next_node]}
                )
                # TODO (Week 3): Re-route using R7 D* Lite instead of fixed 60s wait
                yield self.env.timeout(60.0)
                continue

            vehicle.current_edge = (current_node, next_node)
            self.logger.log(
                self.run_id, self.mode, self.seed, self.scenario, self.rate,
                self.env.now, vehicle.id, "edge_enter", {"edge": [current_node, next_node], "cost": edge_cost}
            )

            # Traversal time is fixed upon entering the edge
            yield self.env.timeout(edge_cost)

            vehicle.current_node = next_node
            vehicle.remaining_route.pop(0)
            vehicle.current_edge = None

            self.logger.log(
                self.run_id, self.mode, self.seed, self.scenario, self.rate,
                self.env.now, vehicle.id, "edge_exit", {"node": next_node}
            )

            # Serve Stop if Node matches an Order
            if next_node in stops_by_node:
                order = stops_by_node[next_node]
                arrival_abs = self.start_time_s + self.env.now

                # Wait for Time Window
                if arrival_abs < order.tw_start:
                    yield self.env.timeout(order.tw_start - arrival_abs)
                if self.env.now < order.release_time:
                    yield self.env.timeout(order.release_time - self.env.now)

                # Capacity Check
                if vehicle.load + order.demand > vehicle.capacity:
                    self.logger.log(
                        self.run_id, self.mode, self.seed, self.scenario, self.rate,
                        self.env.now, vehicle.id, "capacity_blocked", {"order_id": order.id, "demand": order.demand}
                    )
                else:
                    yield self.env.timeout(order.service_time)
                    vehicle.load += order.demand
                    self.logger.log(
                        self.run_id, self.mode, self.seed, self.scenario, self.rate,
                        self.env.now, vehicle.id, "stop_served", {"order_id": order.id, "load": vehicle.load}
                    )
                    del stops_by_node[next_node]

    def add_vehicle(self, vehicle: Vehicle, stops: List[Order]):
        self.vehicles[vehicle.id] = vehicle
        self.env.process(self.vehicle_process(vehicle, stops))

    def run(self, duration_seconds: float = 14400.0):
        self.logger.log(self.run_id, self.mode, self.seed, self.scenario, self.rate, 0.0, "env", "sim_start", {})
        
        self.env.process(self.event_gen.generate_poisson_events(
            rate_per_hour=self.rate, 
            total_duration_s=duration_seconds
        ))
        
        self.env.run(until=duration_seconds)
        
        self.logger.log(self.run_id, self.mode, self.seed, self.scenario, self.rate, self.env.now, "env", "sim_complete", {})