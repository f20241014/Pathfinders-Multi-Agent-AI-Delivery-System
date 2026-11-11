import json
import os
from typing import Any, Dict

from src.sim.interfaces import MetricsLogger


class SimulationLogger(MetricsLogger):
    """Writes one JSON line per event; schema in docs/log_schema.md."""

    def __init__(
        self,
        log_path: str,
        run_id: str,
        mode: str,
        seed: int,
        scenario: str,
        rate: float,
        file_mode: str = "w",
    ):
        self.log_path = log_path
        self.run_id = run_id
        self.mode = mode
        self.seed = seed
        self.scenario = scenario
        self.rate = rate
        dirname = os.path.dirname(self.log_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        # "w" truncates any old log so each run starts clean.
        with open(self.log_path, file_mode, encoding="utf-8"):
            pass

    def log(
        self,
        event_type: str,
        timestamp: float,
        payload: Dict[str, Any],
        agent_id: str = "env",
    ) -> None:
        record = {
            "run_id": self.run_id,
            "mode": self.mode,
            "seed": self.seed,
            "scenario": self.scenario,
            "rate": self.rate,
            "t": round(float(timestamp), 2),
            "agent_id": agent_id,
            "event": event_type,
            "payload": payload,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
