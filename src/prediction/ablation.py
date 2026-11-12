"""R6 ablation: predictor ON vs OFF, independent mode, same scenario and seed.
PILOT seeds only (9001+). Keep them out of the final test seeds."""
import argparse, copy, json
from pathlib import Path
import numpy as np, pandas as pd, yaml
from src.search.heuristics import make_heuristic
from src.sim.agent_planner import AgentPlanner
from src.sim.environment import DEFAULT_DURATION_S, DeliverySimEnvironment
from src.sim.run import assign_orders, build_order, build_vehicle
from src.sim.world import DEFAULT_MAP_PATH, World


def run_one(config, run_id, on, rate, seed, log_dir):
    cfg = copy.deepcopy(config)
    cfg.update(run_id=run_id, mode="independent", seed=seed,
               disruption_rate_per_hour=float(rate),
               log_path=str(log_dir / f"{run_id}.jsonl"))
    world = World.from_defaults(cfg.get("map_path", DEFAULT_MAP_PATH), seed=seed)
    if on:
        assert world.predictor is not None, "predictor failed to load"
    else:
        world.predictor = None
    env = DeliverySimEnvironment(world, cfg)
    vehicles = [build_vehicle(v) for v in cfg.get("vehicles", [])]
    orders = [build_order(o) for o in cfg.get("orders", [])]
    for o in orders:
        env.add_order(o)
    assign = assign_orders(vehicles, orders)
    planner = AgentPlanner(env, mode="independent",
                           heuristic=make_heuristic(world.graph()))
    for v in vehicles:
        planner.register(v, assign[v.id])
    for v in vehicles:
        env.add_vehicle(v, assign[v.id])
    env.run(float(cfg.get("duration_seconds", DEFAULT_DURATION_S)))
    planner.finish()
    meta = {o.id: o for o in orders}
    rows = [json.loads(x) for x in open(env.log_path) if x.strip()]
    done = [(r["t"], meta.get(r["payload"].get("order_id")))
            for r in rows if r["event"] == "order_delivered"]
    done = [(t, o) for t, o in done if o is not None]
    return {"delivered": len(done),
            "failed": sum(r["event"] == "order_failed" for r in rows),
            "replans": sum(r["event"] == "replan" for r in rows),
            "mean_delivery_s": float(np.mean([t - max(o.release_time, float(cfg.get("start_time_s", 21600))) for t, o in done])) if done else np.nan,
            "on_time_rate": sum(t <= o.tw_end for t, o in done) / max(len(orders), 1)}


def boot(d, n=2000, seed=0):
    d = np.asarray(d, float); d = d[~np.isnan(d)]
    r = np.random.default_rng(seed)
    m = [r.choice(d, len(d)).mean() for _ in range(n)]
    return d.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/viz_demo.yaml")
    ap.add_argument("--rates", type=float, nargs="+", default=[10.0])
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    config = yaml.safe_load(open(a.config))
    log_dir = Path("logs"); log_dir.mkdir(exist_ok=True)
    out = []
    for rate in a.rates:
        for k in range(a.seeds):
            seed = 9001 + k
            for on in (True, False):
                tag = "on" if on else "off"
                m = run_one(config, f"abl_{tag}_r{rate:g}_s{seed}", on, rate, seed, log_dir)
                out.append({"rate": rate, "seed": seed, "predictor": tag, **m})
                print(out[-1], flush=True)
    df = pd.DataFrame(out)
    df.to_csv("reports/ablation_predictor_pilot.csv", index=False)
    for rate, g in df.groupby("rate"):
        on = g[g.predictor == "on"].set_index("seed"); off = g[g.predictor == "off"].set_index("seed")
        for col in ("mean_delivery_s", "on_time_rate", "delivered"):
            m, lo, hi = boot((off[col] - on[col]).values)
            print(f"rate {rate:g} | {col}: off minus on = {m:.3f}  95% CI [{lo:.3f}, {hi:.3f}]")


if __name__ == "__main__":
    main()
