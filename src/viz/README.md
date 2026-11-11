# src/viz (R2)

| file | what |
|------|------|
| `plot_route.py` | one A* route on the Secunderabad map -> `docs/route_example.png` |
| `replay.py` | replay of a simulator JSONL log on the map (GIF/MP4 or PNG snapshot) |
| `demo_scenario.py` | writes `configs/viz_demo.yaml`, a 10-vehicle, 30-order demo for the replay |

## Replay (Week 4)

```bash
python -m src.viz.demo_scenario --vehicles 10 --orders 30 --seed 7
python -m src.sim.run --config configs/viz_demo.yaml
python -m src.viz.replay --log logs/viz_demo.jsonl --config configs/viz_demo.yaml \
    [--snapshot-t 06:33 --png docs/replay_example.png]
```

Output: `reports/replay/<run_id>.mp4` if ffmpeg is on PATH, else `.gif` (not committed).

Colours: vehicle blue = driving, red = waiting at a closure, grey = stationary;
order hollow = open, green = delivered, red x = failed; thick red road + ring = closed;
yellow to red road = traffic spike (by multiplier).

For reuse (Week 5 three-pane view): `load_log(path)` -> events, `state_at(events, t,
config, graph)` -> plain `ReplayState` (no matplotlib), `ReplayRenderer(ax, graph)`
draws the base map once and `update(state)` moves the dynamic artists.

Measured on the 10-vehicle, 4 h demo: 481 frames in 46.4 s (0.096 s per frame).

The state rules, timings, and gaps (straight-line motion, dynamic orders not drawn,
messages n/a, order locations from the config, single run only) are in
[`docs/replay_viz.md`](../../docs/replay_viz.md).

## Side-by-side replay (Week 5)

| file | what |
|------|------|
| `multipane.py` | 2 or 3 logs side by side on one clock, per-pane HUD, negotiation flashes, playback keys |
| `demo_pair.py` | demo runs for the viewer: `viz_demo` without and with R7's planner (not the experiment) |

```bash
python -m src.viz.demo_pair                       # logs/pair_noreplan.jsonl, logs/pair_independent.jsonl
python -m src.viz.multipane --logs logs/pair_noreplan.jsonl logs/pair_independent.jsonl     --labels "no replanning" "independent" --config configs/viz_demo.yaml --show
```

Logs with a different scenario or seed are refused (`--allow-mismatch` renders them under a
red "NOT A COMPARISON" banner). Keys in `--show`: space pause, `+`/`-` speed 0.25x-16x,
arrows step one frame, `r` restart. Messages show `n/a (not logged)` when a log has no
message rows: no code logs them yet, and the negotiation event contract is an assumption
to confirm with R5, R1 and R8. Details, timings and gaps: [`docs/multipane_viz.md`](../../docs/multipane_viz.md).
