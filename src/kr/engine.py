"""
R3 · Forward-chaining production-rule engine (written from scratch, no rule library).

Pieces:
  WorkingMemory  facts = dicts with a "type" key; each fact gets an integer id
  Rule           name, salience, match(wm) -> activations, act(wm, binding)
  Agenda         all (rule, binding) pairs whose conditions hold now
  Cycle          match -> pick highest-salience activation -> fire -> repeat
                 until nothing new can fire (quiescence)

Conflict resolution: higher salience first; ties broken by rule order, then by recency of the facts
(newer first). Refraction: an activation (rule, key) fires at most once, so the loop always ends.

Every firing is written to the explanation trace, which is what feasible() returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable


class WorkingMemory:
    def __init__(self):
        self._facts: dict[int, dict] = {}
        self._next_id = 0

    def assert_fact(self, ftype: str, **attrs) -> int:
        fid = self._next_id
        self._next_id += 1
        self._facts[fid] = {"type": ftype, "_id": fid, **attrs}
        return fid

    def retract(self, fid: int) -> None:
        self._facts.pop(fid, None)

    def facts(self, ftype: str | None = None) -> list[dict]:
        return [f for f in self._facts.values() if ftype is None or f["type"] == ftype]

    def one(self, ftype: str) -> dict | None:
        fs = self.facts(ftype)
        return fs[0] if fs else None

    def exists(self, ftype: str, **attrs) -> bool:
        return any(all(f.get(k) == v for k, v in attrs.items()) for f in self.facts(ftype))


@dataclass
class Activation:
    key: tuple  # identifies the binding (used for refraction)
    binding: Any  # passed to the action
    recency: int = 0  # max fact id involved; larger = newer


@dataclass
class Rule:
    name: str  # e.g. "R01"
    description: str
    salience: int
    match: Callable[[WorkingMemory], Iterable[Activation]]
    act: Callable[[WorkingMemory, Any], str]  # returns a one-line message for the trace


class Engine:
    def __init__(self, rules: list[Rule], max_cycles: int = 10_000):
        self.rules = rules
        self.order = {r.name: i for i, r in enumerate(rules)}
        self.max_cycles = max_cycles

    def run(self, wm: WorkingMemory) -> list[str]:
        fired: set[tuple] = set()
        trace: list[str] = []
        for _ in range(self.max_cycles):
            agenda = [
                (r, a) for r in self.rules for a in r.match(wm) if (r.name, a.key) not in fired
            ]
            if not agenda:
                return trace
            rule, act = max(
                agenda, key=lambda ra: (ra[0].salience, -self.order[ra[0].name], ra[1].recency)
            )
            fired.add((rule.name, act.key))
            msg = rule.act(wm, act.binding)
            if msg:
                trace.append(f"{rule.name}: {msg}")
        raise RuntimeError(
            "rule engine did not reach quiescence (check for rules that keep asserting new facts)"
        )
