from typing import Dict, Any, List
import numpy as np
import simpy
from src.sim.models import Vehicle, Order
from src.sim.logger import SimulationLogger


class DeliverySimEnvironment:
    def __init__(self, world, config: Dict[str, Any]):
        self.world = world
        self.config = config
        self.env = simpy.Environment()
        self.start_time_s = config.get("start_time_s", 21600.0)
        self.seed = config.get("seed", 42)
        self.rng = np.random.default_rng(self.seed)
        log_path = config.get("log_path", "logs/sim.jsonl")
        self.logger = SimulationLogger(log_path)
        self.vehicles: Dict[str, Vehicle] = {}
        self.orders: List[Order] = []

    def get_current_time(self) -> float:
        return self.start_time_s + self.env.now

    def add_order(self, order: Order):
        """Add order to environment for R3 integration."""
        self.orders.append(order)

    def log_event(self, event_type: str, payload: dict):
        abs_t = self.get_current_time()
        self.logger.log(event_type, abs_t, payload)

    def add_vehicle(
        self, vehicle: Vehicle, assigned_orders: List[Order]
    ):
        self.vehicles[vehicle.id] = vehicle
        for o in assigned_orders:
            if o not in self.orders:
                self.orders.append(o)
        self.env.process(
            self._vehicle_process(vehicle, list(assigned_orders))
        )

    def _vehicle_process(
        self, vehicle: Vehicle, assigned_orders: List[Order]
    ):
        pending_orders = list(assigned_orders)
        retry_queue: List[Order] = []

        while vehicle.remaining_route:
            next_node = vehicle.remaining_route.pop(0)
            u = vehicle.current_node
            v = next_node

            # Road disruption wait loop
            while True:
                curr_t = self.get_current_time()
                if self.world.is_blocked(u, v, 0, curr_t):
                    self.log_event(
                        "blocked_wait",
                        {"vehicle_id": vehicle.id, "edge": (u, v, 0)},
                    )
                    yield self.env.timeout(60.0)
                else:
                    break

            curr_t = self.get_current_time()
            travel_time = self.world.edge_time(u, v, 0, curr_t)
            self.log_event(
                "edge_enter",
                {
                    "vehicle_id": vehicle.id,
                    "edge": (u, v, 0),
                    "expected_duration": travel_time,
                },
            )
            yield self.env.timeout(travel_time)
            vehicle.current_node = v

            node_orders = [o for o in pending_orders if o.node == v]
            for order in node_orders:
                curr_t = self.get_current_time()
                # Time window check
                if curr_t > order.tw_end:
                    self.log_event(
                        "order_failed",
                        {
                            "order_id": order.id,
                            "reason": "time_window_missed",
                            "tw_end": order.tw_end,
                        },
                    )
                    pending_orders.remove(order)
                    continue

                # Capacity check and retry deferral
                if vehicle.load + order.demand > vehicle.capacity:
                    self.log_event(
                        "capacity_blocked",
                        {
                            "vehicle_id": vehicle.id,
                            "order_id": order.id,
                            "demand": order.demand,
                            "capacity": vehicle.capacity,
                        },
                    )
                    if order not in retry_queue:
                        retry_queue.append(order)
                    continue

                vehicle.load += order.demand
                yield self.env.timeout(order.service_time)
                self.log_event(
                    "order_delivered",
                    {"vehicle_id": vehicle.id, "order_id": order.id},
                )
                pending_orders.remove(order)
                if order in retry_queue:
                    retry_queue.remove(order)

        # Mark unservable deferred orders as order_failed
        for order in retry_queue:
            self.log_event(
                "order_failed",
                {
                    "order_id": order.id,
                    "reason": "capacity_exceeded_unservable",
                },
            )

    def run(self, duration_seconds: float):
        disruption_rate = self.config.get(
            "disruption_rate_per_hour", 0.0
        )
        if disruption_rate > 0.0:
            from src.sim.events import EventGenerator
            gen = EventGenerator(
                self.env,
                self.rng,
                self.world,
                lambda e: self.logger.log(
                    e.event_type, e.t, e.payload
                ),
                start_time_s=self.start_time_s,
            )
            self.env.process(
                gen.schedule_disruptions(
                    disruption_rate, duration_seconds
                )
            )
        self.env.run(until=duration_seconds)
