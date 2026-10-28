import json
import os
from typing import Dict, Any

class SimulationLogger:

    def __init__(self, output_path: str = "docs/sim_log.jsonl"):
        self.output_path = output_path
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        with open(self.output_path, "w") as f:
            pass

    def log(self, event_type: str, timestamp: float, data: Dict[str, Any]):
        entry = {
            "timestamp": round(timestamp, 2),
            "event_type": event_type,
            "data": data
        }
        with open(self.output_path, "a") as f:
            f.write(json.dumps(entry) + "\n")