"""Week 1 executable CVRP exercise, using the official OR-Tools pattern."""
from ortools.constraint_solver import pywrapcp, routing_enums_pb2


def solve_toy():
    """Serve four unit demands using two capacity-two vehicles; return node routes."""
    matrix = [[0, 1, 2, 3, 4], [1, 0, 1, 2, 3], [2, 1, 0, 1, 2],
              [3, 2, 1, 0, 1], [4, 3, 2, 1, 0]]
    manager = pywrapcp.RoutingIndexManager(5, 2, 0)
    routing = pywrapcp.RoutingModel(manager)
    transit = routing.RegisterTransitCallback(
        lambda a, b: matrix[manager.IndexToNode(a)][manager.IndexToNode(b)])
    routing.SetArcCostEvaluatorOfAllVehicles(transit)
    demand = routing.RegisterUnaryTransitCallback(
        lambda a: int(manager.IndexToNode(a) != 0))
    routing.AddDimensionWithVehicleCapacity(demand, 0, [2, 2], True, 'Capacity')
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.time_limit.FromMilliseconds(100)
    solution = routing.SolveWithParameters(params)
    if solution is None:
        raise RuntimeError('toy CVRP has no solution')
    routes = []
    for v in range(2):
        route, index = [], routing.Start(v)
        while not routing.IsEnd(index):
            route.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        routes.append(route + [0])
    return routes


if __name__ == '__main__':
    print(solve_toy())
