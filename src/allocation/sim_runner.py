"""Executable R4 integration harness on the existing SimPy environment/world.

Uses shortest snapshot paths to exercise allocation. It is not R7 D* Lite or R5
negotiation, and must not be used as the project's three-condition final study.
"""
import argparse
import json

from src.allocation.cost_model import VehicleState
from src.allocation.runtime import AllocationController
from src.allocation.world_adapter import WorldTravel
from src.sim.environment import DeliverySimEnvironment
from src.sim.models import Order, Vehicle


class AllocationSimulation(DeliverySimEnvironment):
    """Separate opt-in runner; preserves R1's default hand-authored route runner."""

    def __init__(self, world, config):
        super().__init__(world, config)
        self.states, self.terminal = [], {}
        self.wakeup = self.env.event()
        self.controller = None

    def add_vehicle(self, vehicle, assigned_orders=None):
        if assigned_orders:
            raise ValueError('register orders with add_order; allocation owns assignments')
        if vehicle.id in self.vehicles:
            raise ValueError('duplicate vehicle')
        self.vehicles[vehicle.id] = vehicle
        self.states.append(VehicleState(vehicle))

    def _emit(self, kind, now, payload):
        self.logger.log(kind, now, payload)
        if kind == 'order_failed':
            self.terminal[payload['order_id']] = 'failed'

    def _wake(self):
        event, self.wakeup = self.wakeup, self.env.event()
        if not event.triggered:
            event.succeed()

    def handle_event(self, event):
        super().handle_event(event)
        self.controller.event(event.t)
        self._wake()

    def _arrive(self, order):
        delay = max(0, order.release_time - self.get_current_time())
        yield self.env.timeout(delay)
        self.controller.event(self.get_current_time(), order)
        self._wake()

    def _drive(self, state):
        v = state.vehicle
        while True:
            if not state.orders:
                yield self.wakeup
                continue
            order = state.orders[0]
            now = self.get_current_time()
            if v.current_node == order.node:
                state.orders.pop(0)  # active service is committed; never reallocate it
                ready = max(now, order.tw_start, order.release_time)
                if ready > order.tw_end or v.load + order.demand > v.capacity:
                    self._emit('order_failed', now, {'order_id': order.id,
                                                     'reason': 'service_infeasible'})
                    continue
                self.controller.busy[v.id] = (v.current_node, ready + order.service_time,
                                              order.demand)
                yield self.env.timeout(ready + order.service_time - now)
                v.load += order.demand
                self.controller.busy.pop(v.id, None)
                self.terminal[order.id] = 'delivered'
                self.log_event('order_delivered', {'order_id': order.id}, v.id)
                continue
            travel = WorldTravel(self.world, now)
            _, path = travel.path(v, v.current_node, order.node)
            if len(path) < 2:
                state.orders.pop(0)
                self._emit('order_failed', now, {'order_id': order.id, 'reason': 'unreachable'})
                continue
            u, target = path[:2]
            key = self.world.edge_key(u, target)
            seconds = self.world.edge_time(u, target, now, key)
            v.current_edge = (u, target, key)
            self.controller.busy[v.id] = (target, now + seconds, 0)
            self.log_event('edge_enter', {'edge': [u, target, key],
                                          'expected_duration': seconds}, v.id)
            yield self.env.timeout(seconds)
            v.current_node, v.current_edge = target, None
            self.controller.busy.pop(v.id, None)
            self.log_event('edge_exit', {'node': target}, v.id)

    def run(self, duration_seconds=None):
        if self.controller is not None:
            raise RuntimeError('runner is single-use')
        self.controller = AllocationController(
            self.world, self.states, self.mode, self._emit,
            time_limit_s=float(self.config.get('solver_time_limit_s', 2)))
        for s in self.states:
            self.env.process(self._drive(s))
        for order in self.orders:
            self.env.process(self._arrive(order))
        duration = duration_seconds or float(self.config.get('duration_seconds', 14400))
        # R1 EventGenerator emits observed spikes/closures via handle_event.
        super().run(duration)
        for order in self.orders:
            if order.id not in self.terminal:
                self._emit('order_failed', self.get_current_time(),
                           {'order_id': order.id, 'reason': 'horizon_exceeded'})
        self.n_delivered = sum(x == 'delivered' for x in self.terminal.values())
        self.n_failed = sum(x == 'failed' for x in self.terminal.values())
        self.log_event('allocation_summary', {'delivered': self.n_delivered,
                                              'failed': self.n_failed})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['centralized', 'independent', 'full'],
                        default='centralized')
    parser.add_argument('--log', default='logs/r4-demo.jsonl')
    args = parser.parse_args()
    import networkx as nx
    from src.sim.world import FakeWorld
    graph = nx.MultiDiGraph()
    for u in range(6):
        for v in range(6):
            if u != v:
                graph.add_edge(u, v, free_flow_time=abs(u-v)*5, highway='primary')
    sim = AllocationSimulation(FakeWorld(graph), dict(mode=args.mode, log_path=args.log,
                                                      start_time_s=0, solver_time_limit_s=0.1))
    for i in range(2):
        sim.add_vehicle(Vehicle(str(i), 0, 5, 0))
    for i in range(1, 6):
        sim.add_order(Order(str(i), i, 1, release_time=i*3, service_time=2))
    sim.run(300)
    print(json.dumps({'delivered': sim.n_delivered, 'failed': sim.n_failed,
                      'log': sim.log_path}))


if __name__ == '__main__':
    main()
