"""R4 mode/event adapter: explicit boundary for R1's simulator and R7 planners."""
from dataclasses import replace

from src.allocation.central_vrp import CentralVRP
from src.allocation.contract_net import ContractNet
from src.allocation.cost_model import VehicleState, validate
from src.allocation.world_adapter import WorldTravel


class AllocationController:
    """Own unstarted orders; caller owns movement, service and committed edges.

    busy[id] = (next/current node, available_at, demand reserved by active service).
    Emit callback uses the existing logger signature (event, absolute_t, payload).
    Full and independent share R4 allocation; R5/R7 coordination is external.
    """

    def __init__(self, world, states, mode, emit=None, time_limit_s=2, feasibility=None):
        if mode not in ('centralized', 'independent', 'full'):
            raise ValueError('unknown mode')
        validate(states, [o for s in states for o in s.orders])
        self.world, self.states, self.mode = world, states, mode
        self.emit, self.time_limit_s, self.feasibility = emit, time_limit_s, feasibility
        self.known = {o.id for s in states for o in s.orders}
        self.failed, self.busy = {}, {}

    def snapshots(self):
        snapshots = []
        for s in self.states:
            node, ready, reserved = self.busy.get(
                s.vehicle.id, (s.vehicle.current_node, s.available_at, 0))
            vehicle = replace(s.vehicle, current_node=node, current_edge=None,
                              load=s.vehicle.load + reserved)
            snapshots.append(VehicleState(vehicle, list(s.orders), ready))
        return snapshots

    def event(self, now, new_order=None):
        """Call for new orders AND every observed disruption/forecast refresh."""
        if new_order is not None and new_order.id in self.known:
            raise ValueError('duplicate order arrival')
        snapshots = self.snapshots()
        travel = WorldTravel(self.world, now)

        def emit(kind, payload):
            if self.emit:
                self.emit(kind, now, payload)

        if new_order is not None:
            validate(snapshots, [new_order])
            self.known.add(new_order.id)
        if self.mode == 'centralized':
            orders = [o for s in snapshots for o in s.orders]
            if new_order is not None:
                orders.append(new_order)
            result = CentralVRP(travel, self.time_limit_s, feasibility=self.feasibility,
                                emit=emit).resolve(snapshots, orders, now)
            for s in snapshots:
                s.orders = result.routes[s.vehicle.id]
            for oid in result.failed:
                self.failed[oid] = 'central_unassigned'
                emit('order_failed', {'order_id': oid, 'reason': self.failed[oid]})
        elif new_order is not None:
            result = ContractNet(travel, self.feasibility, emit).allocate(new_order, snapshots, now)
            if result.vehicle_id is None:
                self.failed[new_order.id] = result.reason
                emit('order_failed', {'order_id': new_order.id, 'reason': result.reason})
        else:
            # Local road replanning is R7's job, not a new allocation auction.
            return None
        for original, planned in zip(self.states, snapshots):
            original.orders = planned.orders
        emit('allocation_complete', {'cpu_seconds': result.cpu_seconds,
                                     'messages': result.messages, 'mode': self.mode})
        return result
