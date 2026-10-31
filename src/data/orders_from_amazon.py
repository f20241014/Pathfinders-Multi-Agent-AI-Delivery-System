
"""
Generate synthetic delivery orders using Amazon Last Mile
package statistics and local Secunderabad graph nodes.
"""

import json
import random
from pathlib import Path

import ijson
import math
import statistics
import networkx as nx
from datetime import datetime
from decimal import Decimal


ROOT = Path(__file__).resolve().parents[2]

PACKAGE_FILE = ROOT / "data" / "cleaned" / "package_data.json"
GRAPH_FILE = ROOT / "data" / "processed" / "secunderabad.graphml"



def load_package_statistics():
    """Read Amazon data route-by-route with bounded memory."""

    MAX_SAMPLES = 5000

    service_times = []
    dimensions = []
    time_window_widths = []

    counts = {
        "packages": 0,
        "service": 0,
        "dimensions": 0,
        "windows": 0
    }

    rng = random.Random(42)

    def reservoir_add(sample, value, seen):
        """Keep at most MAX_SAMPLES random observations."""
        if len(sample) < MAX_SAMPLES:
            sample.append(value)
        else:
            index = rng.randrange(seen)
            if index < MAX_SAMPLES:
                sample[index] = value

    with open(PACKAGE_FILE, "rb") as file:

        # Process one route at a time.
        for route_id, route in ijson.kvitems(file, ""):

            for stop in route.values():
                for package in stop.values():

                    counts["packages"] += 1

                    service = package.get(
                        "planned_service_time_seconds"
                    )

                    if isinstance(service, (int, float, Decimal)) and service > 0:
                        counts["service"] += 1
                        reservoir_add(
                            service_times,
                            float(service),
                            counts["service"]
                        )

                    dim = package.get("dimensions", {})

                    if all(
                        isinstance(dim.get(k), (int, float, Decimal))
                        for k in ("depth_cm", "height_cm", "width_cm")
                    ):
                        counts["dimensions"] += 1

                        reservoir_add(
                            dimensions,
                            [
                                dim["depth_cm"],
                                dim["height_cm"],
                                dim["width_cm"]
                            ],
                            counts["dimensions"]
                        )

                    window = package.get("time_window", {})
                    start = window.get("start_time_utc")
                    end = window.get("end_time_utc")

                    if isinstance(start, str) and isinstance(end, str):

                        start_dt = datetime.strptime(
                            start, "%Y-%m-%d %H:%M:%S"
                        )

                        end_dt = datetime.strptime(
                            end, "%Y-%m-%d %H:%M:%S"
                        )

                        width = (
                            end_dt - start_dt
                        ).total_seconds() / 3600

                        if width > 0:
                            counts["windows"] += 1

                            reservoir_add(
                                time_window_widths,
                                width,
                                counts["windows"]
                            )

    print("Packages processed:", counts["packages"])
    print("Packages with time windows:", counts["windows"])

    print("Service-time samples:", len(service_times))
    print("Dimension samples:", len(dimensions))
    print("Time-window samples:", len(time_window_widths))

    return {
        "service_times": service_times,
        "dimensions": dimensions,
        "time_window_widths": time_window_widths,
        "time_window_probability": (
            counts["windows"] / counts["packages"]
            if counts["packages"] else 0
        ),
        "total_packages": counts["packages"]
    }



def load_local_nodes():
    """Load nodes from the local Secunderabad road graph."""

    graph = nx.read_graphml(GRAPH_FILE)

    nodes = list(graph.nodes())

    if not nodes:
        raise ValueError("No nodes found in the local road graph.")

    return nodes


def generate_orders(number_of_orders=100, seed=42):
    """Generate synthetic orders using Amazon empirical statistics."""

    random.seed(seed)

    stats = load_package_statistics()
    nodes = load_local_nodes()

    orders = []

    for i in range(number_of_orders):

        service_time = random.choice(stats["service_times"])
        dimensions = random.choice(stats["dimensions"])

        has_window = (
            random.random() < stats["time_window_probability"]
        )

        if has_window:
            width = random.choice(stats["time_window_widths"])
            tw_start = random.uniform(0, max(0, 24 - width))
            tw_end = tw_start + width
        else:
            tw_start = -1.0
            tw_end = -1.0

        order = {
            "id": f"O{i + 1}",
            "node": int(random.choice(nodes)),
            "demand": float(math.prod(dimensions)),
            "priority": random.choices(
                [1, 2, 3],
                weights=[0.2, 0.5, 0.3]
            )[0],
            "tw_start": tw_start,
            "tw_end": tw_end,
            "service_time": float(service_time),
            "release_time": 0.0,
            "dimensions_cm": [float(x) for x in dimensions]
        }

        orders.append(order)

    return orders


def print_order_summary(orders):
    """Print a summary of generated delivery orders."""

    print("\n--- ORDER SUMMARY ---")
    print("Total orders:", len(orders))

    print(
        "Priority distribution:",
        {
            p: sum(o["priority"] == p for o in orders)
            for p in [1, 2, 3]
        }
    )

    print(
        "Orders with time windows:",
        sum(o["tw_start"] is not None for o in orders)
    )

    print(
        "Average service time:",
        round(statistics.mean([o["service_time"] for o in orders]), 2),
        "seconds"
    )

    print(
        "Average package volume:",
        round(statistics.mean([o["demand"] for o in orders]), 2),
        "cm3"
    )

    print(
        "Unique delivery nodes:",
        len(set(o["node"] for o in orders))
    )





from dataclasses import dataclass


@dataclass
class GeneratedOrder:
    id: str
    node: int
    demand: float
    priority: int
    tw_start: float
    tw_end: float
    service_time: float
    release_time: float


def convert_to_sim_orders(generated_orders):
    """Convert generated dictionaries into simulation-compatible objects."""

    return [
        GeneratedOrder(
            id=order["id"],
            node=int(order["node"]),
            demand=float(order["demand"]),
            priority=int(order["priority"]),
            tw_start=float(order["tw_start"]),
            tw_end=float(order["tw_end"]),
            service_time=float(order["service_time"]),
            release_time=float(order["release_time"])
        )
        for order in generated_orders
    ]




if __name__ == "__main__":
    generated = generate_orders(100)

    print("Generated orders:", len(generated))
    print_order_summary(generated)
    print("First order:", generated[0])
