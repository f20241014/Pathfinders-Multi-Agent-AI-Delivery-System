# Side-by-side replay, viz v2 (R2, Week 5)

`src/viz/multipane.py` plays two or three simulator logs (format: `docs/log_schema.md`)
next to each other on one shared clock, on the Secunderabad road map. Each pane is the
Week 4 replay (`src/viz/replay.py`, unchanged): at every frame time `t` each pane calls
`state_at(its own events, t, config, graph)` and draws with its own `ReplayRenderer`.
The new file adds the comparison checks, a richer HUD per pane, negotiation flashes and
playback keys.

## How to run (from the repo root)

```bash
# 1. Demo pair: same config, seed and rate, without and with R7's planner
#    (writes logs/pair_noreplan.jsonl and logs/pair_independent.jsonl)
python -m src.viz.demo_pair                      # --rate 120 by default (stress setting)

# 2. Live window with playback keys
python -m src.viz.multipane --logs logs/pair_noreplan.jsonl logs/pair_independent.jsonl \
    --labels "no replanning (R1 sim only)" "independent (R7 AgentPlanner)" \
    --config configs/viz_demo.yaml --show

# 3. Or a video (reports/replay/multipane_<run ids>.gif, .mp4 with ffmpeg) / one PNG
python -m src.viz.multipane --logs logs/pair_noreplan.jsonl logs/pair_independent.jsonl \
    --labels "no replanning" "independent" --config configs/viz_demo.yaml --end 07:00
python -m src.viz.multipane --logs logs/pair_noreplan.jsonl logs/pair_independent.jsonl \
    --labels "no replanning" "independent" --config configs/viz_demo.yaml \
    --snapshot-t 06:28 --png reports/replay/pair_0628.png
```

Options: `--step 30` (sim seconds per frame), `--fps 15`, `--dpi 80`, `--start` / `--end`
(HH:MM or seconds from midnight), `--out <path>`, `--layout row|column` (side by side, or
stacked), `--allow-mismatch` (see below). A third log is added with a third `--logs` path
and a third `--labels` string. Rendered files go to `reports/replay/` and are not
committed. At 06:28 in the demo pair the left pane shows V7 and V8 red (waiting together
at a closed road, 10 waits so far, 0 replans) and the right pane shows V8 already done
and V7 driving (0 waits, 314 replans).

## Playback keys (`--show`)

| key | action |
|-----|--------|
| space | pause / resume |
| `+` (or `=`) / `-` | faster / slower: 0.25x, 0.5x, 1x, 2x, 4x, 8x, 16x |
| right / left arrow | pause and step one frame forward / back |
| `r` | restart from the start time |

The current state and speed are printed in the header line, for example
`PAUSED  speed 2x (60 sim-s/frame)`. Speed changes how many sim seconds one frame
advances (`--step` x speed), not the timer interval. matplotlib's own bindings for the
arrow keys and `r` (back / forward / home view) are switched off in the window so they do
not clash. Offline rendering (GIF/MP4/PNG) has no keys: its speed is `--step` sim seconds
per frame at `--fps`, printed in the header.

`FuncAnimation` runs with `blit=False`, as in `replay.py` (the brief said "with blit as
replay.py does", but `replay.py` uses `blit=False`). Blitting only repaints the inside of
each axes; the HUDs and the clock sit outside them, so with blit they would smear. Every
frame is a full redraw, so the live window cannot reach 15 fps with two or three panes
(see the timings): it plays as fast as it can draw.

## Rules

### Same scenario and seed, or stop

All non-empty logs must have the same `scenario` and `seed` (from the log keys of the
first row). If they differ, the program stops with an error naming each log's scenario and
seed, before loading the map. `--allow-mismatch` renders them anyway, but prints a red
banner across the top of the figure ("logs are NOT from the same scenario and seed ...
NOT A COMPARISON") and a warning in the terminal, and the header then drops the scenario
and seed line. Different scenarios are never compared silently. `mode` and `run_id` are
expected to differ and are not checked; `rate` is not checked either (shown in each HUD).

### One clock

The shared clock runs over the union of the logs' time ranges (`time_range` of each
non-empty log: `sim_start`/`duration_seconds` if logged, else first/last `t`). If every
log is empty it falls back to the config's `start_time_s` and `duration_seconds`. A pane
whose log ended earlier keeps its last state and its HUD adds `(this log ended at HH:MM)`.
The spike colour scale is the same in all panes (the largest `max_spike` / magnitude over
all logs), so equal colours mean equal multipliers.

### HUD per pane

The Week 4 HUD (`hud_text`, with its fixed `messages: n/a`) is hidden; each pane has its
own:

```
<label>
mode: <from the log>   rate: <n>/h   seed: <n>
orders: d delivered / f failed / n total
closures active: a   spikes active: s
waits at closed roads: <blocked_wait rows up to t>   replans: <replan rows up to t>
trigger: on | off | n/a        <- latest trigger_toggle row up to t; n/a if none
messages: n/a (not logged)     <- or: messages: T (alloc a, req q, resp p, result r)
negotiation flashes: k active, u not drawn      <- only when messages are logged
```

"waits" counts rows, and the simulator writes one `blocked_wait` row every 60 s while a
vehicle stands at a closed road, so it measures waiting time in minutes summed over
vehicles, not the number of separate stops. "replans" counts R7's `replan` rows: one per
agent whose route changed, so one closure can add several.

### The n/a rule for messages

`message_counts_at(events, t)` counts the four D7 types: `allocation`,
`negotiation_request`, `negotiation_response`, `negotiation_result`. Each row adds
`payload.get("count", 1)`. Only rows with `t <= t_now` count. If the log has **no** row of
any of these types (anywhere in the log), the function returns `None` and the HUD shows
`messages: n/a (not logged)`, because showing `0` would claim that no messages were sent.
If the log has message rows but none yet at `t`, the HUD shows `0`, which is then true.

## Negotiation event contract (an assumption, to confirm with R5, R1 and R8)

No code logs message rows yet (see Gaps). The viewer assumes this contract; nothing in
the log schema guarantees it, so it must be agreed with **R5** (who sends the messages),
**R1** (who owns the log schema, `docs/log_schema.md`) and **R8** (who counts them for the
metrics):

| event | agent_id | payload (assumed) |
|-------|----------|-------------------|
| `allocation` | env or vehicle | `{"count": int (optional, default 1), ...}` |
| `negotiation_request` | vehicle | `{"count": int (optional, default 1), ...}` |
| `negotiation_response` | vehicle | `{"count": int (optional, default 1), ...}` |
| `negotiation_result` | vehicle or env | `{"count": int (optional), "edge": [u, v, key] (optional), "vehicles": [ids] (optional)}` |

Flash rule (`flashes_at`): a `negotiation_result` row at `t0` is active while
`t0 <= t < t0 + 60` (sim seconds). It is drawn as an orange ring
1. at the midpoint of `payload.edge` if both nodes are on the map; else
2. at the current position of each vehicle in `payload.vehicles` that is on the map; else
3. not drawn, and counted in the HUD as `u not drawn`, so a missing position is visible
   instead of silently dropped.

`count` is how many messages one row stands for (so R5 can log one row per round instead
of one per message). If R5 logs one row per message, `count` is simply left out.

## Measured performance

**Prediction (given before measuring, by Prudhvi (R2)):** "2x and 3x, so roughly 0.19 s and
0.29 s per frame, as it should scale linearly" (from the Week 4 single pane, 0.096 s).

**Measured** (one Windows 11 laptop, Python 3.14.5, matplotlib 3.11.2, no ffmpeg so GIF
via Pillow, `--dpi 80`, `--step 30`, 06:00-07:00 = 121 frames, the busy hour of the demo
pair; `time.perf_counter`, 5 runs each, median of the per-run seconds per frame):

| panes | logs | s/frame (median) | 5 runs | vs 1 pane | predicted |
|-------|------|------------------|--------|-----------|-----------|
| 1 (`replay.py`) | pair_independent | **0.105** | 0.105, 0.103, 0.105, 0.105, 0.105 | 1.00x | (0.096) |
| 2 | pair_noreplan + pair_independent | **0.153** | 0.156, 0.153, 0.152, 0.153, 0.156 | 1.46x | 0.19 (2x) |
| 3 | + pair_independent again, labelled `PLACEHOLDER: same log` | **0.221** | 0.223, 0.222, 0.220, 0.221, 0.221 | 2.10x | 0.29 (3x) |

The single pane was re-timed in the same session instead of using Week 4's 0.096 s
(different log, a busier hour, another day): 0.105 s.

**The prediction was wrong**: time grows with the number of panes, but less than
linearly (1.46x and 2.10x, not 2x and 3x). Each extra pane added about 0.05-0.07 s.

**Where the time goes** (medians per frame, from the same runs):

| | 2 panes | 3 panes |
|-|---------|---------|
| compute: `state_at` + counters + flashes, all panes | 3.1 ms (2%) | 4.3 ms (2%) |
| of which `state_at` alone (separate loop) | 1.4 ms | 2.0 ms |
| moving the artists (`set_offsets`, HUD text) | 0.8 ms | 1.1 ms |
| `grab_frame` (matplotlib draws the figure, copies pixels) | 111.9 ms (73%) | 156.9 ms (71%) |
| rest: Pillow writes the GIF when the file is closed | about 37 ms | about 59 ms |
| update + `canvas.draw()` only, no writer (separate loop) | 106.3 ms | 146.0 ms |

So almost all the time is matplotlib drawing (and then GIF encoding); `state_at`
rescanning the whole log every frame costs 1-2 ms and is not worth optimising. Why the
growth is less than linear was not measured. Two likely reasons, both unconfirmed: part
of each draw is per figure (one canvas, one clear, one pixel copy), not per pane, and
the figures differ in size (one pane is 8 x 9.8 in = 78 in², two panes 11.2 x 8.6 =
96 in², three 16.8 x 8.6 = 144 in²: 1.23x and 1.85x the pixels).

Consequence for `--show`: one frame of three panes takes about 0.15 s to draw, so the
window shows about 6-7 frames per second, not 15.

## Gaps

- **No real three-condition logs.** The plan's three conditions (independent,
  centralized, full) need R1's mode switch in `src/sim/run.py`, R5's trigger and
  negotiation hook, and R7's planner to be connected. Until then the only real pair is the
  demo pair below, and a three-pane run can only reuse a log; the measurement above
  labels the third pane `PLACEHOLDER: same log` so it cannot be read as a comparison.
- **Message events do not exist yet.** `src/coordination/messages.py` and
  `negotiation.py` count messages in memory (`MessageCounter`), and `AgentPlanner` keeps
  only a number (`negotiation_messages`); nothing writes a message row to the JSONL. Every
  real log shows `messages: n/a (not logged)` and no flashes. The flash and count code is
  tested only on hand-made logs.
- **The demo pair is not the experiment.** `src/viz/demo_pair.py` runs
  `configs/viz_demo.yaml` (10 vehicles, 30 orders, seed 7) at 120 disruptions per hour, a
  stress setting picked so the panes show something. The `rate` also covers `new_order`
  events (341 disruptions + 132 new orders in 4 h). Condition (a) is labelled
  `no_replanning`, which is not one of the plan's modes; it is the plain R1 simulator.
  Results from it are not experiment results.
- **Same seed, but the disruptions may differ.** The closure guard (D11) depends on where
  vehicles still need to go, which the planner changes, so the random stream can drift
  apart between two runs. In the demo pair it did not (341 of 341 disruption rows
  identical); `demo_pair.py` prints this check every run.
- **Fleet finish time hides the difference.** In the demo pair both runs resolve their
  last order at 06:36:53 (the last order belongs to a vehicle no closure touched), while
  V8 finishes at 06:37 without replanning and 06:24 with it. Per-vehicle times are a
  better measure than one fleet finish time.
- **Dynamic orders are counted, not served.** The 14 dynamic orders released by 06:28
  raise "total" (44 = 30 + 14) but never get delivered (TODO(R3) in
  `src/sim/events.py`, unchanged from Week 4).
- **Replans keep a waiting vehicle waiting.** R1's vehicle process pops the next node
  before checking for a closure, so a vehicle already waiting at a closed road keeps
  waiting even if a replan gives it a new route (read from
  `src/sim/environment.py`, not tested). In the demo pair it did not show: the planner
  run has 0 `blocked_wait` rows. Noted for R1 and R7, not changed here.
- **The window cannot keep up with `--fps`** because every frame is a full redraw
  (`blit=False`, see above).
- Everything listed in `docs/replay_viz.md` (straight-line motion, order locations from
  the config) still applies to each pane.
