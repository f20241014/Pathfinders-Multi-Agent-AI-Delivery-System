
"""
R3 - Forward Chaining Rule Engine

Implements:
1. Working memory
2. Rule conditions and actions
3. Agenda
4. Forward chaining
5. Explanation trace
"""

from dataclasses import dataclass
from typing import Callable
from src.kr.rules import road_allowed
from src.kr.rules import sort_orders_by_priority


# ==========================================
# 1. RULE REPRESENTATION
# ==========================================

@dataclass
class Rule:
    name: str
    condition: Callable
    action: Callable
    priority: int = 1


# ==========================================
# 2. WORKING MEMORY
# ==========================================

class WorkingMemory:
    """Stores facts used by the rule engine."""

    def __init__(self, initial_facts=None):
        self.facts = dict(initial_facts or {})
        self.trace = []

    def get(self, key, default=None):
        return self.facts.get(key, default)

    def set(self, key, value):
        self.facts[key] = value

    def add_trace(self, message):
        self.trace.append(message)


# ==========================================
# 3. RULE ENGINE
# ==========================================

class ForwardChainingEngine:

    def __init__(self, rules):
        self.rules = sorted(
            rules,
            key=lambda rule: rule.priority
        )

    def run(self, memory):
        """
        Repeatedly match and execute applicable rules.

        Rules are fired once per execution.
        """

        fired = set()

        while True:

            # Build agenda from rules whose conditions match.
            agenda = [
                rule for rule in self.rules
                if rule.name not in fired
                and rule.condition(memory)
            ]

            if not agenda:
                break

            # Select highest-priority rule.
            rule = agenda[0]

            memory.add_trace(
                f"ACTIVATED: {rule.name}"
            )

            # Execute rule action.
            rule.action(memory)

            memory.add_trace(
                f"EXECUTED: {rule.name}"
            )

            fired.add(rule.name)

        return memory


# ==========================================
# 4. DELIVERY RULE DEFINITIONS
# ==========================================

def capacity_condition(memory):
    return "capacity_ok" in memory.facts


def capacity_action(memory):
    if not memory.get("capacity_ok"):
        memory.set("feasible", False)
        memory.add_trace("REJECTED: Vehicle capacity exceeded.")
    else:
        memory.add_trace("PASSED: Vehicle capacity is sufficient.")


def time_window_condition(memory):
    return "time_window_ok" in memory.facts


def time_window_action(memory):
    if not memory.get("time_window_ok"):
        memory.set("feasible", False)
        memory.add_trace("REJECTED: Invalid time window.")
    else:
        memory.add_trace("PASSED: Time windows are valid.")


def road_condition(memory):
    return "road_allowed" in memory.facts


def road_action(memory):
    if not memory.get("road_allowed"):
        memory.set("feasible", False)
        memory.add_trace("REJECTED: Road access restricted.")
    else:
        memory.add_trace("PASSED: Road access permitted.")


def shift_condition(memory):
    return "shift_ok" in memory.facts


def shift_action(memory):
    if not memory.get("shift_ok"):
        memory.set("feasible", False)
        memory.add_trace("REJECTED: Maximum shift duration exceeded.")
    else:
        memory.add_trace("PASSED: Shift duration is valid.")


# ==========================================
# 5. RULE BASE
# ==========================================

DELIVERY_RULES = [

    Rule(
        name="CAPACITY_RULE",
        condition=capacity_condition,
        action=capacity_action,
        priority=1
    ),

    Rule(
        name="ROAD_ACCESS_RULE",
        condition=road_condition,
        action=road_action,
        priority=2
    ),

    Rule(
        name="TIME_WINDOW_RULE",
        condition=time_window_condition,
        action=time_window_action,
        priority=3
    ),

    Rule(
        name="SHIFT_LIMIT_RULE",
        condition=shift_condition,
        action=shift_action,
        priority=4
    )
]


# ==========================================
# 6. PUBLIC EXECUTION FUNCTION
# ==========================================

def run_engine(facts):
    """
    Run the forward-chaining engine.

    Parameters:
        facts: Dictionary containing feasibility facts.

    Returns:
        Dictionary containing final facts and explanation trace.
    """

    initial_facts = dict(facts)
    initial_facts.setdefault("feasible", True)

    memory = WorkingMemory(initial_facts)

    engine = ForwardChainingEngine(DELIVERY_RULES)

    engine.run(memory)

    return {
        "feasible": memory.get("feasible"),
        "facts": memory.facts,
        "trace": memory.trace
    }


# ==========================================
# 7. INTEGRATION WITH REAL R1 OBJECTS
# ==========================================

from src.kr.rules import evaluate_rules


def run_feasibility_engine(vehicle, orders, edges=None):
    # Arrange deliveries: High priority first
    orders = sort_orders_by_priority(orders)
    """
    Connect R1 Vehicle and Order objects to the
    forward-chaining engine.

    Returns:
        {
            "feasible": bool,
            "trace": list,
            "facts": dict
        }
    """

    # Evaluate actual delivery constraints.
    _, rule_results = evaluate_rules(vehicle, orders)

        # Check road access if route edges are provided
    if edges is not None:
        road_passed, road_trace = check_road_access(vehicle, edges)

        rule_results.append({
            "rule": "ROAD_ACCESS",
            "passed": road_passed,
            "message": (
                "All roads are accessible"
                if road_passed
                else "Route contains a restricted road"
            )
        })

    # Store the evaluated results in working memory.
    memory = WorkingMemory({
        "feasible": True,
        "rule_results": rule_results,
        "processed_rules": []
    })

    # Create an agenda rule for every evaluated constraint.
    agenda_rules = []

    for result in rule_results:

        rule_name = result["rule"]

        def condition(mem, name=rule_name):
            return name not in mem.get("processed_rules", [])

        def action(mem, current=result):
            mem.get("processed_rules").append(current["rule"])

            if not current["passed"]:
                mem.set("feasible", False)

                mem.add_trace(
                    f"REJECTED: {current['rule']} - "
                    f"{current['message']}"
                )
            else:
                mem.add_trace(
                    f"PASSED: {current['rule']} - "
                    f"{current['message']}"
                )

        agenda_rules.append(
            Rule(
                name=rule_name,
                condition=condition,
                action=action
            )
        )

    # Run forward chaining.
    engine = ForwardChainingEngine(agenda_rules)
    engine.run(memory)

    return {
        "feasible": memory.get("feasible"),
        "facts": memory.facts,
        "trace": memory.trace
    }

def check_road_access(vehicle, edges):
    """
    Check whether all roads in the proposed route are allowed.
    Returns (passed, trace).
    """
    trace = []

    for edge in edges:
        passed = road_allowed(vehicle, edge)

        trace.append({
            "rule": "ROAD_ACCESS",
            "edge": edge,
            "passed": passed,
            "message": (
                "Road access allowed"
                if passed
                else "Road access restricted"
            )
        })

        if not passed:
            return False, trace

    return True, trace



if __name__ == "__main__":

    example_facts = {
        "capacity_ok": True,
        "road_allowed": True,
        "time_window_ok": True,
        "shift_ok": True
    }

    result = run_engine(example_facts)

    print("FEASIBLE:", result["feasible"])

    print("\nEXPLANATION TRACE:")
    for message in result["trace"]:
        print("-", message)
