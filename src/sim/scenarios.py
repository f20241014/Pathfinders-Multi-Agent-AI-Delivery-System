# src/sim/scenarios.py
import numpy as np
from src.search.astar import astar
from src.search.heuristics import make_heuristic

def make_demo_config(world, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    nodes = list(world.graph().nodes())
    
    depot = int(rng.choice(nodes))
    stop1 = int(rng.choice(nodes))
    stop2 = int(rng.choice(nodes))

    h = make_heuristic(world.graph())
    res1 = astar(world.graph(), depot, stop1, heuristic=h)
    res2 = astar(world.graph(), stop1, stop2, heuristic=h)

    route = res1.path + res2.path[1:]

    return {
        "run_id": "sim_demo",
        "seed": seed,
        "scenario": "secunderabad_demo",
        "mode": "independent",
        "duration_seconds": 14400.0,
        "start_time_s": 21600.0,
        "disruption_rate_per_hour": 5.0,
        "headless": True,
        "vehicles": [
            {
                "id": "V1",
                "depot_node": depot,
                "capacity": 100.0,
                "current_node": depot,
                "route": route
            }
        ],
        "orders": [
            {
                "id": "O1",
                "node": stop1,
                "demand": 15.0,
                "priority": 1,
                "tw_start": 21600.0,
                "tw_end": 28800.0,
                "service_time": 300.0,
                "release_time": 0.0
            },
            {
                "id": "O2",
                "node": stop2,
                "demand": 20.0,
                "priority": 2,
                "tw_start": 21600.0,
                "tw_end": 28800.0,
                "service_time": 300.0,
                "release_time": 0.0
            }
        ]
    }