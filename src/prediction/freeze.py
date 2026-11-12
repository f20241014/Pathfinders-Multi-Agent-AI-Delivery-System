"""Freeze record for the predictor (R6): file hash, config hash, size, speed."""
import hashlib
import json
import os
import time

import torch

from src.prediction.predictor import Predictor
from src.prediction.train import CFG
from src.world.traffic_model import TrafficModel

PATH = "models/lstm_v1.pt"


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


tm = TrafficModel.from_graph()
p = Predictor(tm, PATH)
times = []
for k in range(20):
    t0 = time.process_time()
    p._compute(100 + k)
    times.append(time.process_time() - t0)
out = {
    "model_file": PATH,
    "model_sha256": sha256_file(PATH),
    "config_sha256": hashlib.sha256(
        json.dumps(CFG, sort_keys=True).encode()).hexdigest(),
    "model_bytes": os.path.getsize(PATH),
    "parameters": sum(x.numel() for x in p.model.parameters()),
    "edges": p.n_edges,
    "refresh_seconds_mean": round(sum(times) / len(times), 4),
    "refresh_seconds_max": round(max(times), 4),
    "torch_version": torch.__version__,
}
with open("reports/model_freeze.json", "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
