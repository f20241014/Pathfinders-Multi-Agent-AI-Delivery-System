"""Real-map R4 smoke check: 10 vehicles/100 synthetic orders, free-flow only."""
import json
from pathlib import Path
import random
from src.allocation.central_vrp import CentralVRP
from src.allocation.contract_net import ContractNet
from src.allocation.cost_model import VehicleState, schedule
from src.allocation.world_adapter import WorldTravel
from src.sim.models import Order, Vehicle
from src.sim.world import World
from src.world.graph_loader import load_road_graph


def main():
    graph = load_road_graph('secunderabad')
    rng = random.Random(404)  # pilot-only
    nodes = rng.sample(sorted(graph.nodes), 103)
    orders = [Order(str(i), node, 1, tw_end=100000, service_time=10)
              for i, node in enumerate(nodes[3:])]
    states = [VehicleState(Vehicle(str(i), nodes[i % 3], 20, nodes[i % 3]))
              for i in range(10)]
    travel = WorldTravel(World(graph), 0)
    cnp = ContractNet(travel)
    messages = 0
    for order in orders:
        messages += cnp.allocate(order, states).messages
    cnp_travel = sum(schedule(s, s.orders, travel).travel_seconds for s in states)
    central = CentralVRP(travel, 2).resolve(states, orders)
    assert sum(len(os) for os in central.routes.values()) + len(central.failed) == 100
    assert all(schedule(s, central.routes[s.vehicle.id], travel).feasible for s in states)
    result = dict(graph_nodes=len(graph), graph_edges=graph.number_of_edges(),
                  vehicles=10, orders=100, demand='synthetic unit demand', seed=404,
                  traffic='free flow only; no predictor or held-out traffic data',
                  cnp_assigned=sum(len(s.orders) for s in states), cnp_travel_s=cnp_travel,
                  cnp_messages=messages, central_failed=len(central.failed),
                  central_travel_s=central.travel_seconds, central_cpu_s=central.cpu_seconds,
                  central_objective=central.objective, central_messages=central.messages)
    path = Path('reports/r4/map_smoke.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
