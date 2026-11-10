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
