"""Bounded OR-Tools CVRPTW reference from current, potentially partial, state."""
from dataclasses import dataclass, field
import math
from time import process_time

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from src.allocation.cost_model import schedule, validate


@dataclass
class CentralResult:
    routes: dict = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    travel_seconds: float = 0.0
    objective: int | None = None
    cpu_seconds: float = 0.0
    messages: int = 0
    status: str = ''


class CentralVRP:
    """Open routes, integer-second conservative timing, scaled capacity.

    Current node must be the NEXT node for an en-route vehicle, available_at its
    known edge-exit time. Caller excludes delivered/actively served orders.
    Forecast snapshot is shared with CNP; no future incident information.
    """

    def __init__(self, travel, time_limit_s=2.0, drop_penalty=100000,
                 feasibility=None, emit=None):
        if not math.isfinite(time_limit_s) or time_limit_s <= 0:
            raise ValueError('positive finite solver limit required')
        if not isinstance(drop_penalty, int) or drop_penalty <= 0:
            raise ValueError('positive integer drop penalty required')
        self.travel = travel
        self.time_limit_s = time_limit_s
        self.drop_penalty = drop_penalty
        self.feasibility = feasibility
        self.emit = emit

    def resolve(self, states, orders, now=0):
        start = process_time()
        validate(states, orders)
        if any(s.vehicle.current_edge is not None for s in states):
            raise ValueError('snapshot en-route vehicles at next node with available_at')
        result = CentralResult(routes={s.vehicle.id: [] for s in states},
                               messages=2 * len(states))
        for s in states:
            if self.emit:
                self.emit('central_state_report', {'sender': s.vehicle.id})
        if not states or not orders:
            result.failed = [o.id for o in orders]
            result.status = 'empty'
            return self._finish(result, states, start)
        # Distinct indices preserve multiple orders at the same road node.
        n, count = len(orders), len(states)
        nodes = [o.node for o in orders] + [s.vehicle.current_node for s in states] + [None]
        sink = len(nodes) - 1
        starts = list(range(n, n + count))
        manager = pywrapcp.RoutingIndexManager(len(nodes), count, starts, [sink] * count)
        routing = pywrapcp.RoutingModel(manager)
        horizon = max(1, math.ceil(max([now] + [o.tw_end for o in orders]
                                      + [s.available_at for s in states]))) + 86400
        callbacks = []  # retain Python closures for the lifetime of the solver
        time_callbacks = []
        for state in states:
            matrix = []
            for a in nodes:
                row = []
                for b in nodes:
                    seconds = 0 if b is None or a is None else self.travel(state.vehicle, a, b)
                    if seconds < 0:
                        raise ValueError('negative travel time')
                    row.append(math.ceil(seconds) if math.isfinite(seconds) else horizon + 1)
                matrix.append(row)

            def transit(a, b, matrix=matrix):
                return matrix[manager.IndexToNode(a)][manager.IndexToNode(b)]

            def duration(a, b, matrix=matrix):
                i, j = manager.IndexToNode(a), manager.IndexToNode(b)
                service = math.ceil(orders[i].service_time) if i < n else 0
                return matrix[i][j] + service

            callbacks.extend([transit, duration])
            cost_cb = routing.RegisterTransitCallback(transit)
            time_callbacks.append(routing.RegisterTransitCallback(duration))
            routing.SetArcCostEvaluatorOfVehicle(cost_cb, len(time_callbacks) - 1)
        routing.AddDimensionWithVehicleTransits(time_callbacks, horizon, horizon, False, 'Time')
        time_dim = routing.GetDimensionOrDie('Time')
        for v, state in enumerate(states):
            ready = math.ceil(max(now, state.available_at))
            time_dim.CumulVar(routing.Start(v)).SetRange(ready, ready)
        for i, order in enumerate(orders):
            index = manager.NodeToIndex(i)
            lo = math.ceil(max(now, order.tw_start, order.release_time))
            hi = math.floor(order.tw_end)
            if lo > hi:
                routing.ActiveVar(index).SetValue(0)
            else:
                time_dim.CumulVar(index).SetRange(lo, hi)
            routing.AddDisjunction([index], self.drop_penalty * order.priority)
        # Rounding demand up / remaining capacity down never silently overloads.
        demands = [math.ceil(o.demand * 1000) for o in orders]
        demand_cb = routing.RegisterUnaryTransitCallback(
            lambda a: demands[manager.IndexToNode(a)] if manager.IndexToNode(a) < n else 0)
        capacities = [math.floor((s.vehicle.capacity - s.vehicle.load) * 1000) for s in states]
        routing.AddDimensionWithVehicleCapacity(demand_cb, 0, capacities, True, 'Capacity')
        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
        params.time_limit.FromMilliseconds(max(1, round(self.time_limit_s * 1000)))
        solution = routing.SolveWithParameters(params)
        result.status = str(routing.status())
        if solution is None:
            result.failed = [o.id for o in orders]
            return self._finish(result, states, start)
        result.objective = solution.ObjectiveValue()
        served = set()
        for v, state in enumerate(states):
            route, index = [], routing.Start(v)
            while not routing.IsEnd(index):
                i = manager.IndexToNode(index)
                if i < n:
                    route.append(orders[i])
                index = solution.Value(routing.NextVar(index))
            checked = schedule(state, route, self.travel, now, self.feasibility)
            if checked.feasible:
                result.routes[state.vehicle.id] = route
                result.travel_seconds += checked.travel_seconds
                served.update(o.id for o in route)
        result.failed = [o.id for o in orders if o.id not in served]
        return self._finish(result, states, start)

    def _finish(self, result, states, start):
        for s in states:
            if self.emit:
                self.emit('central_plan_broadcast', {'recipient': s.vehicle.id,
                          'order_ids': [o.id for o in result.routes[s.vehicle.id]]})
        result.cpu_seconds = process_time() - start
        return result
