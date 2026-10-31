
"""
R3 - Delivery Feasibility Rules

Compatible with R1's Order and Vehicle dataclasses.
No duplicate dataclasses are defined here.
"""

import math


def check_capacity(vehicle, orders):
    """Check total assigned demand against available vehicle capacity."""

    capacity = vehicle.capacity
    current_load = vehicle.current_load
    required = sum(order.demand for order in orders)

    valid = (
        math.isfinite(capacity)
        and math.isfinite(current_load)
        and math.isfinite(required)
        and capacity >= 0
        and current_load >= 0
        and required >= 0
    )

    passed = valid and current_load + required <= capacity

    return {
        "rule": "CAPACITY",
        "passed": passed,
        "message": (
            f"Vehicle {vehicle.id}: current load={current_load}, "
            f"new demand={required}, capacity={capacity}"
        )
    }


def check_non_negative_demand(orders):
    """Reject negative or non-finite order demand."""

    passed = all(
        math.isfinite(order.demand) and order.demand >= 0
        for order in orders
    )

    return {
        "rule": "NON_NEGATIVE_DEMAND",
        "passed": passed,
        "message": "All order demands must be finite and non-negative."
    }


def check_time_windows(orders):
    """Check validity of specified time-window boundaries."""

    for order in orders:
        start = order.tw_start
        end = order.tw_end

        # Missing time windows are allowed.
        if start is None or end is None:
            continue

        if not math.isfinite(start) or not math.isfinite(end):
            return {
                "rule": "TIME_WINDOW",
                "passed": False,
                "message": f"Invalid time-window values for {order.id}"
            }

        if start > end:
            return {
                "rule": "TIME_WINDOW",
                "passed": False,
                "message": f"Start time exceeds end time for {order.id}"
            }

    return {
        "rule": "TIME_WINDOW",
        "passed": True,
        "message": "All specified time windows are valid."
    }


def check_service_times(orders):
    """Check that service times are non-negative and finite."""

    passed = all(
        math.isfinite(order.service_time)
        and order.service_time >= 0
        for order in orders
    )

    return {
        "rule": "SERVICE_TIME",
        "passed": passed,
        "message": "Service times must be finite and non-negative."
    }


def check_release_times(orders):
    """Check that release times are finite and non-negative."""

    passed = all(
        math.isfinite(order.release_time)
        and order.release_time >= 0
        for order in orders
    )

    return {
        "rule": "RELEASE_TIME",
        "passed": passed,
        "message": "Release times must be finite and non-negative."
    }


def evaluate_rules(vehicle, orders):
    """
    Evaluate the currently supported feasibility rules.

    Returns:
        feasible: bool
        trace: list of rule results
    """

    results = [
        check_non_negative_demand(orders),
        check_capacity(vehicle, orders),
        check_time_windows(orders),
        check_service_times(orders),
        check_release_times(orders)
    ]

    feasible = all(result["passed"] for result in results)

    return feasible, results


def feasible(vehicle, order_set):
    """
    Public R3 feasibility interface.

    Returns:
        (bool, trace)
    """

    return evaluate_rules(vehicle, order_set)


# Provisional road-access policy.
# Update this mapping when the project defines vehicle-specific restrictions.

ALLOWED_ROAD_CLASSES = {
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
}


def road_allowed(vehicle, edge):
    """
    Check whether a vehicle can use a road edge.

    The current provisional policy allows all listed road
    classes except motorway.

    edge can be a road-class string or an edge dictionary
    containing a 'highway' or 'road_class' field.
    """
    if isinstance(edge, dict):
        road_class = edge.get("road_class", edge.get("highway"))
    else:
        road_class = edge

    if isinstance(road_class, list):
        road_class = road_class[0] if road_class else None

    if not isinstance(road_class, str):
        return False

    road_class = road_class.replace("_link", "").strip().lower()

    return road_class in ALLOWED_ROAD_CLASSES


def sort_orders_by_priority(orders):
    """
    Sort orders by priority.
    Lower priority number means higher importance:
    1 = High, 2 = Medium, 3 = Low.
    """
    return sorted(orders, key=lambda order: order.priority)


def check_shift_duration(shift_start, shift_end, max_shift_duration):
    """
    Check whether a vehicle's shift duration is within its limit.
    All three values must use the same time unit.
    """
    if shift_end < shift_start:
        return {
            "rule": "SHIFT_DURATION",
            "passed": False,
            "message": "Invalid shift times"
        }

    duration = shift_end - shift_start

    passed = duration <= max_shift_duration

    return {
        "rule": "SHIFT_DURATION",
        "passed": passed,
        "message": (
            f"Shift duration {duration} is within the limit"
            if passed
            else f"Shift duration {duration} exceeds the limit"
        )
    }



