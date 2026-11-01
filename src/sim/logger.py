# src/sim/logger.py
import json
import os
from typing import Dict, Any, Optional


class SimulationLogger:
    def __init__(self, run_id: str = "default_run", output_path: Optional[str] = None):
        if output_path is None:
            output_path = f"logs/{run_id}.jsonl"
        self.output_path = output_path
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

    def log(self, run_id: str, mode: str, seed: int, scenario: str, rate: float,
            t: float, agent_id: str, event: str, payload: Dict[str, Any]):
        entry = {
            "run_id": run_id,
            "mode": mode,
            "seed": seed,
            "scenario": scenario,
            "rate": rate,
            "t": round(t, 2),
            "agent_id": agent_id,
            "event": event,
            "payload": payload
        }
        with open(self.output_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
