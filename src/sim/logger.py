import json
import os
from typing import Dict, Any
from src.sim.interfaces import MetricsLogger


class SimulationLogger(MetricsLogger):
    def __init__(self, log_path: str, mode: str = "w"):
        self.log_path = log_path
        dirname = os.path.dirname(self.log_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        # Initialize/overwrite log file for clean runs
        with open(self.log_path, mode, encoding="utf-8"):
            pass

    def log(
        self, event_type: str, timestamp: float, payload: Dict[str, Any]
    ) -> None:
        record = {
            "t": timestamp,
            "event_type": event_type,
            "payload": payload,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
