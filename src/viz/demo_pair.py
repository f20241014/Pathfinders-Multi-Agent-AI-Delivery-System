"""Two demo runs for the side-by-side viewer (R2, Week 5). NOT the project's experiment.

    python -m src.viz.demo_pair [--config configs/viz_demo.yaml] [--rate 120] [--prefix pair]

This is a demo of the viewer (src/viz/multipane.py), nothing more. It runs the same
config, same seed and same disruption rate twice:

  (a) logs/<prefix>_noreplan.jsonl     R1's simulator alone, no planner. Mode label in
                                       the log: "no_replanning" (vehicles wait at closed
                                       roads).
  (b) logs/<prefix>_independent.jsonl  the same scenario with R7's AgentPlanner(mode=
                                       "independent") attached as in the "For R1's mode
                                       switch" snippet of src/search/README.md.

--prefix (default "pair") names both files and both run_ids, so a second pair (for
example the 20-vehicle config, --prefix pair20) does not overwrite the first.

The default rate, 120 disruptions per hour, is a STRESS setting chosen so the panes show
something (closures, waits, replans) within a few minutes. It is not an experiment rate;
the experiment's rates are set in the plan, not here.

Same seed does not mean the same disruptions in both runs: the closure guard (D11) looks
at where vehicles still need to go, and the planner changes that, so the random stream can
drift apart after the first rejected closure. The script prints how many disruption rows
the two logs share.

The third condition, "full", needs R5's coordination hook and R1's mode switch in
src/sim/run.py; neither is connected yet, so there is no full-mode log to show.

src/sim/run.py is not changed: the environment is built here, copying run_from_config.
"""
import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any, Dict, List

import yaml

from src.search.heuristics import make_heuristic
from src.sim.agent_planner import AgentPlanner
from src.sim.environment import DEFAULT_DURATION_S, DeliverySimEnvironment
from src.sim.run import assign_orders, build_order, build_vehicle
from src.sim.world import DEFAULT_MAP_PATH, World

DEFAULT_RATE = 120.0
DEFAULT_PREFIX = "pair"
RUNS = (
    # (run_id / file name suffix after "<prefix>_", mode label in the log, R7's planner?)
    ("noreplan", "no_replanning", False),
    ("independent", "independent", True),
)


def run_one(config: Dict[str, Any], run_id: str, mode: str, with_planner: bool,
            rate: float, log_dir: Path) -> Path:
    """Build and run one simulation (same steps as src.sim.run.run_from_config)."""
    cfg = copy.deepcopy(config)
    cfg.update(run_id=run_id, mode=mode, disruption_rate_per_hour=float(rate),
               log_path=str(log_dir / f"{run_id}.jsonl"))
    world = World.from_defaults(cfg.get("map_path", DEFAULT_MAP_PATH),
                                seed=int(cfg.get("seed", 42)))
    env = DeliverySimEnvironment(world, cfg)

    vehicles = [build_vehicle(v) for v in cfg.get("vehicles", [])]
    orders = [build_order(o) for o in cfg.get("orders", [])]
    for order in orders:
        env.add_order(order)
    assignment = assign_orders(vehicles, orders)

    planner = None
    if with_planner:   # the README snippet; coordination=None until R5's hook (W5)
        planner = AgentPlanner(env, mode="independent",
                               heuristic=make_heuristic(world.graph()), coordination=None)
        for vehicle in vehicles:
            planner.register(vehicle, assignment[vehicle.id])
    for vehicle in vehicles:
        env.add_vehicle(vehicle, assignment[vehicle.id])

    env.run(float(cfg.get("duration_seconds", DEFAULT_DURATION_S)))
    if planner is not None:
        planner.finish()
    return Path(env.log_path)     # the logger opens/closes the file per row


def summarize(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    count = {}
    for r in rows:
        count[r["event"]] = count.get(r["event"], 0) + 1
    done = [r["t"] for r in rows if r["event"] in ("order_delivered", "order_failed")]
    return {
        "rows": rows,
        "delivered": count.get("order_delivered", 0),
        "failed": count.get("order_failed", 0),
        "blocked_wait": count.get("blocked_wait", 0),
        "replan": count.get("replan", 0),
        "disruptions": count.get("disruption", 0),
        "finish_t": max(done) if done else None,
    }


def _clock(t) -> str:
    if t is None:
        return "n/a"
    s = int(round(t))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _disruption_keys(rows: List[dict]):
    return [(r["t"], r["payload"]["type"], tuple(r["payload"]["edge"]))
            for r in rows if r["event"] == "disruption"]


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Demo pair of runs for the multipane viewer.")
    parser.add_argument("--config", default="configs/viz_demo.yaml")
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE,
                        help="disruptions per hour (default 120, a stress setting)")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX,
                        help='file/run_id prefix: logs/<prefix>_noreplan.jsonl etc. '
                             '(default "pair")')
    args = parser.parse_args(argv)

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"DEMO of the viewer, not an experiment. config {args.config}, "
          f"seed {config.get('seed')}, rate {args.rate:g}/h (stress setting)")
    summaries = {}
    run_ids = [f"{args.prefix}_{suffix}" for suffix, _, _ in RUNS]
    for run_id, (_, mode, with_planner) in zip(run_ids, RUNS):
        t0 = time.perf_counter()
        path = run_one(config, run_id, mode, with_planner, args.rate, log_dir)
        s = summarize(path)
        summaries[run_id] = s
        print(f"{run_id:19s} mode={mode:14s} delivered {s['delivered']:3d}  "
              f"failed {s['failed']:3d}  blocked_wait {s['blocked_wait']:4d}  "
              f"replan {s['replan']:5d}  disruptions {s['disruptions']:4d}  "
              f"last order resolved {_clock(s['finish_t'])}  "
              f"({time.perf_counter() - t0:.1f} s wall) -> {path}")

    a, b = (_disruption_keys(summaries[r]["rows"]) for r in run_ids)
    same = 0
    for x, y in zip(a, b):
        if x != y:
            break
        same += 1
    print(f"disruptions identical in both logs: the first {same} of {len(a)} / {len(b)}"
          + ("" if same == len(a) == len(b) else
             " (the streams drift apart after that; see the docstring)"))


if __name__ == "__main__":
    main()
