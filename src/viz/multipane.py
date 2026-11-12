"""Side-by-side replay of two or three simulator logs on one clock (R2, Week 5).

Run from the repo root:
    python -m src.viz.multipane --logs logs/pair_noreplan.jsonl logs/pair_independent.jsonl \
        --labels "no replanning" "independent (R7)" --config configs/viz_demo.yaml
    ... --snapshot-t 06:20 --png reports/replay/pair.png      (one PNG frame)
    ... --show                                                (live window with keys)

Every pane is the Week 4 replay (src/viz/replay.py, not changed): each pane calls
state_at(its own events, t, config, graph) at the same shared time t and draws with its
own ReplayRenderer. This file adds only what a comparison needs:
- a check that all logs have the same scenario and seed (stop, unless --allow-mismatch);
- a per-pane HUD with waits, replans, trigger state and message counts;
- negotiation flashes (an orange ring for 60 sim-seconds after a negotiation_result row);
- playback keys for --show.

The message rows (allocation / negotiation_request / negotiation_response /
negotiation_result) are NOT logged by any code yet. Their payload contract here is an
assumption to confirm with R5, R1 and R8; see docs/multipane_viz.md.
"""
import argparse
import itertools
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.viz.replay import (DEFAULT_FPS, DEFAULT_STEP_S, MAX_FRAMES_HINT, OUT_DIR,
                            ReplayRenderer, ReplayState, format_clock, frame_times,
                            load_config, load_graph_for, load_log, parse_time,
                            spike_max_from, state_at, time_range)

MESSAGE_TYPES = ("allocation", "negotiation_request", "negotiation_response",
                 "negotiation_result")
FLASH_S = 60.0                  # a negotiation_result ring stays this many sim-seconds
SHORT_LOG_EVENTS = 5            # fewer events than this: say so in the pane
SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)
FLASH_COLOR = "#ff7f0e"         # orange
WARN_COLOR = "#b00000"
# matplotlib's own key bindings that clash with the playback keys.
_CLASHING_KEYMAPS = ("keymap.back", "keymap.forward", "keymap.home")
_PLAYBACK_KEYS = {"left", "right", "r", " ", "+", "-", "="}


# ---------------------------------------------------------------------------
# Checks across logs
# ---------------------------------------------------------------------------

class LogMismatchError(ValueError):
    """The logs are not from the same scenario and seed, so they cannot be compared."""


def run_key(events) -> Optional[Tuple[str, int]]:
    """(scenario, seed) of a log from its first row; None for an empty log."""
    if not events:
        return None
    return str(events[0]["scenario"]), int(events[0]["seed"])


def check_same_run(event_lists: Sequence[list], labels: Sequence[str],
                   allow_mismatch: bool = False) -> List[str]:
    """Raise LogMismatchError if the non-empty logs differ in scenario or seed.

    With allow_mismatch=True it returns the problem as a warning string instead
    (the caller must print it on the figure). Empty logs have no keys to check.
    """
    keys = {label: run_key(ev) for label, ev in zip(labels, event_lists)}
    present = {k for k in keys.values() if k is not None}
    if len(present) <= 1:
        return []
    detail = "; ".join(f"{label}: scenario={k[0]!r} seed={k[1]}"
                       for label, k in keys.items() if k is not None)
    msg = f"logs are NOT from the same scenario and seed ({detail})"
    if not allow_mismatch:
        raise LogMismatchError(msg + ". They cannot be compared. Use --allow-mismatch "
                               "only to look at them, never to compare them.")
    return [msg]


def shared_range(event_lists: Sequence[list], config: Optional[dict] = None
                 ) -> Tuple[float, float]:
    """One clock for all panes: the union of the logs' time ranges.

    If every log is empty, fall back to the config's start time and duration.
    """
    ranges = [time_range(ev) for ev in event_lists if ev]
    if ranges:
        return min(r[0] for r in ranges), max(r[1] for r in ranges)
    cfg = config or {}
    start = float(cfg.get("start_time_s", 21600.0))
    return start, start + float(cfg.get("duration_seconds", 0.0))


# ---------------------------------------------------------------------------
# Counters (plain data, no matplotlib)
# ---------------------------------------------------------------------------

def _row_count(event) -> int:
    """How many messages a row stands for: payload.count, default 1."""
    return int(event["payload"].get("count", 1))


def message_counts_at(events, t: float) -> Optional[Dict[str, int]]:
    """Messages per D7 type up to time t, plus "total".

    Returns None if the log has no message-type rows at all: then the HUD shows
    "n/a (not logged)", because 0 would claim that no messages were sent.
    """
    if not any(e["event"] in MESSAGE_TYPES for e in events):
        return None
    counts = {k: 0 for k in MESSAGE_TYPES}
    for e in events:
        if e["event"] in counts and float(e["t"]) <= t:
            counts[e["event"]] += _row_count(e)
    counts["total"] = sum(counts[k] for k in MESSAGE_TYPES)
    return counts


def pane_counters(events, t: float) -> Dict[str, Any]:
    """waits (blocked_wait rows), replans (replan rows) and the trigger state up to t.

    trigger is True/False from the latest trigger_toggle row at or before t (the later
    row in the file wins a tie), or None if there is none ("n/a").
    """
    waits = replans = 0
    trigger: Optional[bool] = None
    trigger_t = float("-inf")
    for e in events:
        et = float(e["t"])
        if et > t:
            continue
        name = e["event"]
        if name == "blocked_wait":
            waits += 1
        elif name == "replan":
            replans += 1
        elif name == "trigger_toggle" and et >= trigger_t:
            trigger, trigger_t = bool(e["payload"].get("trigger_enabled")), et
    return {"waits": waits, "replans": replans, "trigger": trigger}


@dataclass
class Flashes:
    points: List[Tuple[float, float]] = field(default_factory=list)   # (lon, lat)
    active: int = 0                 # negotiation_result rows within FLASH_S of t
    undrawn: int = 0                # active rows with no position we can draw


def _edge_mid(graph, edge) -> Optional[Tuple[float, float]]:
    if graph is None or not edge or len(edge) < 2:
        return None
    try:
        u, v = int(edge[0]), int(edge[1])
    except (TypeError, ValueError):
        return None
    if u not in graph or v not in graph:
        return None
    a, b = graph.nodes[u], graph.nodes[v]
    return ((float(a["lon"]) + float(b["lon"])) / 2, (float(a["lat"]) + float(b["lat"])) / 2)


def flashes_at(events, t: float, state: ReplayState, graph=None) -> Flashes:
    """Where to draw negotiation rings at time t.

    A negotiation_result row at t0 is active while t0 <= t < t0 + FLASH_S. It is drawn
    at the midpoint of payload.edge if that edge is on the map; else at the current
    position of each vehicle in payload.vehicles that is on the map; else it is counted
    as undrawn. (Assumed contract: to be confirmed with R5, R1 and R8.)
    """
    out = Flashes()
    for e in events:
        if e["event"] != "negotiation_result":
            continue
        t0 = float(e["t"])
        if not t0 <= t < t0 + FLASH_S:
            continue
        out.active += 1
        p = e["payload"]
        mid = _edge_mid(graph, p.get("edge"))
        if mid is not None:
            out.points.append(mid)
            continue
        pts = []
        for vid in p.get("vehicles") or []:
            vs = state.vehicles.get(str(vid))
            if vs is not None and vs.lat is not None:
                pts.append((vs.lon, vs.lat))
        if pts:
            out.points.extend(pts)
        else:
            out.undrawn += 1
    return out


@dataclass
class PaneFrame:
    """Everything one pane shows at time t (plain data)."""
    t: float
    state: ReplayState
    counters: Dict[str, Any]
    messages: Optional[Dict[str, int]]
    flashes: Flashes


def compute_pane(events, t: float, config=None, graph=None) -> PaneFrame:
    state = state_at(events, t, config, graph)
    return PaneFrame(t=t, state=state, counters=pane_counters(events, t),
                     messages=message_counts_at(events, t),
                     flashes=flashes_at(events, t, state, graph))


def _on_off(value: Optional[bool]) -> str:
    return "n/a" if value is None else ("on" if value else "off")


def pane_hud_text(label: str, frame: PaneFrame, log_end: Optional[float] = None) -> str:
    c, sc, m = frame.counters, frame.state.counters, frame.state.meta
    rate = m.get("rate")
    rate_txt = f"{float(rate):g}/h" if rate is not None else "n/a"
    lines = [
        label,
        f"mode: {m.get('mode', 'n/a')}   rate: {rate_txt}   seed: {m.get('seed', 'n/a')}",
        f"orders: {sc.get('delivered', 0)} delivered / {sc.get('failed', 0)} failed"
        f" / {sc.get('total_orders', 0)} total",
        f"closures active: {sc.get('closures_active', 0)}"
        f"   spikes active: {sc.get('spikes_active', 0)}",
        f"waits at closed roads: {c['waits']}   replans: {c['replans']}",
        f"trigger: {_on_off(c['trigger'])}",
    ]
    msg = frame.messages
    if msg is None:
        lines.append("messages: n/a (not logged)")
    else:
        lines.append(f"messages: {msg['total']} (alloc {msg['allocation']}, "
                     f"req {msg['negotiation_request']}, resp {msg['negotiation_response']}, "
                     f"result {msg['negotiation_result']})")
        f = frame.flashes
        lines.append(f"negotiation flashes: {f.active} active, {f.undrawn} not drawn")
    if log_end is not None and frame.t > log_end:
        lines.append(f"(this log ended at {format_clock(log_end)})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

class PaneView:
    """One pane: the Week 4 ReplayRenderer plus our own HUD, flash rings and a note."""

    def __init__(self, ax, graph, label: str, events: list, spike_max: float,
                 show_legend: bool, config=None):
        self.ax, self.graph, self.label = ax, graph, label
        self.events, self.config = events, config
        self.renderer = ReplayRenderer(ax, graph, spike_max=spike_max, show_legend=show_legend)
        self.renderer.hud.set_visible(False)     # its "messages: n/a" line is replaced
        self.hud = ax.text(0.0, 1.01, "", transform=ax.transAxes, va="bottom", ha="left",
                           fontsize=8, family="monospace", zorder=10, clip_on=False)
        self.flash = ax.scatter([], [], s=420, facecolors="none", edgecolors=FLASH_COLOR,
                                linewidths=2.5, zorder=9)
        self.log_end = time_range(events)[1] if events else None
        note = ""
        if not events:
            note = "empty log: nothing to replay"
        elif len(events) < SHORT_LOG_EVENTS:
            note = f"short log: only {len(events)} event(s)"
        self.note = ax.text(0.5, 0.5, note, transform=ax.transAxes, ha="center", va="center",
                            fontsize=11, color=WARN_COLOR, zorder=11, visible=bool(note),
                            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                                      edgecolor=WARN_COLOR, alpha=0.9))

    def compute(self, t: float) -> PaneFrame:
        return compute_pane(self.events, t, self.config, self.graph)

    def draw(self, frame: PaneFrame) -> List[Any]:
        artists = self.renderer.update(frame.state)
        self.flash.set_offsets(ReplayRenderer._offsets(frame.flashes.points))
        self.hud.set_text(pane_hud_text(self.label, frame, self.log_end))
        return artists + [self.flash, self.hud, self.note]


class MultiPane:
    """The figure: 2-3 PaneViews, one shared clock line, and any mismatch warning."""

    def __init__(self, graph, event_lists: Sequence[list], labels: Sequence[str],
                 config=None, layout: str = "row", warnings: Sequence[str] = ()):
        import matplotlib.pyplot as plt

        n = len(event_lists)
        if not 2 <= n <= 3:
            raise ValueError(f"need 2 or 3 logs, got {n}")
        if len(labels) != n:
            raise ValueError(f"{n} logs but {len(labels)} labels")
        if layout not in ("row", "column"):
            raise ValueError("layout must be 'row' or 'column'")
        top_in = 2.0 + (0.45 if warnings else 0.0)     # clock + warning + HUD, inches
        if layout == "row":
            w, h = 5.6 * n, 8.6 + (0.45 if warnings else 0.0)
            fig, axes = plt.subplots(1, n, figsize=(w, h))
            fig.subplots_adjust(left=0.01, right=0.99, bottom=0.06, top=1 - top_in / h,
                                wspace=0.04)
        else:
            w, h = 7.0, 7.4 * n + (0.45 if warnings else 0.0)
            fig, axes = plt.subplots(n, 1, figsize=(w, h))
            fig.subplots_adjust(left=0.02, right=0.98, bottom=0.5 / h, top=1 - top_in / h,
                                hspace=0.36)
        spike_max = max(spike_max_from(ev, config) for ev in event_lists)  # one colour scale
        self.fig = fig
        self.views = [PaneView(ax, graph, label, ev, spike_max, show_legend=(i == 0),
                               config=config)
                      for i, (ax, label, ev) in enumerate(zip(axes, labels, event_lists))]
        keys = [run_key(ev) for ev in event_lists if ev]
        self.run_text = (f"scenario {keys[0][0]}, seed {keys[0][1]}" if keys
                         else "no events in any log")
        self.clock = fig.text(0.5, 1 - 0.12 / h, "", ha="center", va="top", fontsize=12,
                              weight="bold", family="monospace")
        self.warning = None
        if warnings:
            self.warning = fig.text(
                0.5, 1 - 0.55 / h, "WARNING: " + " | ".join(warnings) +
                "\nNOT A COMPARISON (--allow-mismatch)", ha="center", va="top", fontsize=9.5,
                color="white", weight="bold",
                bbox=dict(boxstyle="round,pad=0.35", facecolor=WARN_COLOR, edgecolor="none"))

    def update(self, t: float, status: str = "") -> Tuple[List[Any], float, float]:
        """Draw every pane at time t. Returns (artists, compute seconds, set seconds)."""
        t0 = time.perf_counter()
        frames = [v.compute(t) for v in self.views]
        t1 = time.perf_counter()
        artists = [self.clock]
        for view, frame in zip(self.views, frames):
            artists += view.draw(frame)
        head = format_clock(t) if self.warning else f"{format_clock(t)}   {self.run_text}"
        self.clock.set_text(f"{head}   {status}" if status else head)
        return artists, t1 - t0, time.perf_counter() - t1


# ---------------------------------------------------------------------------
# Output: snapshot, offline animation, live window
# ---------------------------------------------------------------------------

def render_snapshot(event_lists, labels, graph, t, png_path, config=None, layout="row",
                    warnings=(), dpi=100) -> MultiPane:
    import matplotlib.pyplot as plt
    mp = MultiPane(graph, event_lists, labels, config, layout, warnings)
    mp.update(t, "snapshot")
    Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    mp.fig.savefig(png_path, dpi=dpi, facecolor="white")
    plt.close(mp.fig)
    return mp


def render_animation(event_lists, labels, graph, out_path, config=None, step=DEFAULT_STEP_S,
                     fps=DEFAULT_FPS, start=None, end=None, dpi=80, layout="row",
                     warnings=()) -> Dict[str, float]:
    """Render to .mp4 (ffmpeg) or .gif (Pillow). Returns timings, split into
    compute (state_at + counters + flashes), set (moving artists) and grab
    (matplotlib draw + image encoding)."""
    import matplotlib.pyplot as plt
    from matplotlib.animation import FFMpegWriter, PillowWriter

    run_start, run_end = shared_range(event_lists, config)
    times = frame_times(run_start if start is None else start,
                        run_end if end is None else end, step)
    if len(times) > MAX_FRAMES_HINT:
        print(f"note: {len(times)} frames (> {MAX_FRAMES_HINT}); use a larger --step to cut it")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = FFMpegWriter(fps=fps) if out_path.suffix.lower() == ".mp4" else PillowWriter(fps=fps)

    status = f"{step:g} sim-s per frame, {fps} fps"
    t0 = time.perf_counter()
    mp = MultiPane(graph, event_lists, labels, config, layout, warnings)
    setup = time.perf_counter() - t0
    compute = setting = grab = 0.0
    with writer.saving(mp.fig, str(out_path), dpi=dpi):
        for t in times:
            _, c, s = mp.update(t, status)
            g0 = time.perf_counter()
            writer.grab_frame()
            grab += time.perf_counter() - g0
            compute, setting = compute + c, setting + s
    plt.close(mp.fig)
    elapsed = time.perf_counter() - t0
    return {"frames": len(times), "seconds": elapsed, "seconds_per_frame": elapsed / len(times),
            "setup_seconds": setup, "compute_seconds": compute, "set_seconds": setting,
            "grab_seconds": grab}


class Player:
    """Playback state for --show (no matplotlib, so it can be unit-tested)."""

    def __init__(self, start: float, end: float, step: float):
        self.start, self.end, self.step = start, end, step
        self.t = start
        self.speed_i = SPEEDS.index(1.0)
        self.paused = False

    @property
    def speed(self) -> float:
        return SPEEDS[self.speed_i]

    def advance(self) -> None:
        if self.paused:
            return
        self.t = min(self.t + self.step * self.speed, self.end)
        if self.t >= self.end:
            self.paused = True

    def key(self, key: Optional[str]) -> None:
        if key == " ":
            self.paused = not self.paused
        elif key in ("+", "="):
            self.speed_i = min(self.speed_i + 1, len(SPEEDS) - 1)
        elif key == "-":
            self.speed_i = max(self.speed_i - 1, 0)
        elif key == "right":
            self.paused = True
            self.t = min(self.t + self.step * self.speed, self.end)
        elif key == "left":
            self.paused = True
            self.t = max(self.t - self.step * self.speed, self.start)
        elif key == "r":
            self.t, self.paused = self.start, False

    def status(self) -> str:
        state = "PAUSED" if self.paused else "playing"
        return (f"{state}  speed {self.speed:g}x ({self.step * self.speed:g} sim-s/frame)"
                f"  [space +/- arrows r]")


def show(event_lists, labels, graph, config=None, step=DEFAULT_STEP_S, start=None, end=None,
         fps=DEFAULT_FPS, layout="row", warnings=()):
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    for name in _CLASHING_KEYMAPS:                 # free left/right/r for playback
        plt.rcParams[name] = [k for k in plt.rcParams[name] if k not in _PLAYBACK_KEYS]
    run_start, run_end = shared_range(event_lists, config)
    player = Player(run_start if start is None else start,
                    run_end if end is None else end, step)
    mp = MultiPane(graph, event_lists, labels, config, layout, warnings)
    mp.fig.canvas.mpl_connect("key_press_event", lambda ev: player.key(ev.key))

    def tick(_):
        artists, _, _ = mp.update(player.t, player.status())
        player.advance()
        return artists

    # blit=False, as in replay.py: the HUDs and the clock sit outside the axes, and
    # blitting only restores the inside of each axes, so they would smear.
    anim = FuncAnimation(mp.fig, tick, frames=itertools.count(), interval=1000 / fps,
                         blit=False, cache_frame_data=False)
    plt.show()
    return anim


def default_out(event_lists) -> Path:
    ids = [ev[0]["run_id"] for ev in event_lists if ev] or ["empty"]
    ext = ".mp4" if shutil.which("ffmpeg") else ".gif"
    return OUT_DIR / f"multipane_{'_vs_'.join(ids)}{ext}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Replay 2-3 simulator logs side by side.")
    p.add_argument("--logs", nargs="+", required=True, help="2 or 3 simulator JSONL logs")
    p.add_argument("--labels", nargs="+", required=True, help="one label per log")
    p.add_argument("--config", required=True, help="sim config YAML (map, depots, orders)")
    p.add_argument("--step", type=float, default=DEFAULT_STEP_S, help="sim seconds per frame")
    p.add_argument("--fps", type=int, default=DEFAULT_FPS)
    p.add_argument("--dpi", type=int, default=80)
    p.add_argument("--start", help="first frame, HH:MM or seconds from midnight")
    p.add_argument("--end", help="last frame, HH:MM or seconds from midnight")
    p.add_argument("--out", help="video path (.mp4 needs ffmpeg, else .gif)")
    p.add_argument("--snapshot-t", help="save one frame at this time (HH:MM or s)")
    p.add_argument("--png", help="snapshot path (default reports/replay/multipane.png)")
    p.add_argument("--show", action="store_true", help="live window with playback keys")
    p.add_argument("--allow-mismatch", action="store_true",
                   help="render logs with different scenario/seed (warning on the figure)")
    p.add_argument("--layout", choices=("row", "column"), default="row")
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if not 2 <= len(args.logs) <= 3:
        raise SystemExit(f"--logs: need 2 or 3 logs, got {len(args.logs)}")
    if len(args.labels) != len(args.logs):
        raise SystemExit(f"--labels: {len(args.logs)} logs but {len(args.labels)} labels")

    import matplotlib
    if not args.show:
        matplotlib.use("Agg")

    event_lists = [load_log(path) for path in args.logs]
    try:   # before loading the map: fail fast
        warnings = check_same_run(event_lists, args.labels, args.allow_mismatch)
    except LogMismatchError as e:
        raise SystemExit(f"error: {e}")
    for w in warnings:
        print(f"WARNING: {w}. Rendering anyway because of --allow-mismatch; "
              "this is NOT a comparison.")
    config = load_config(args.config)
    graph = load_graph_for(config)
    start = parse_time(args.start) if args.start else None
    end = parse_time(args.end) if args.end else None
    common = dict(config=config, layout=args.layout, warnings=warnings)

    if args.snapshot_t is not None:
        png = Path(args.png) if args.png else OUT_DIR / "multipane.png"
        t = parse_time(args.snapshot_t)
        t0 = time.perf_counter()
        render_snapshot(event_lists, args.labels, graph, t, png, **common)
        print(f"snapshot {format_clock(t)} -> {png} ({time.perf_counter() - t0:.2f} s)")
    if args.show:
        show(event_lists, args.labels, graph, step=args.step, start=start, end=end,
             fps=args.fps, **common)
        return
    if args.snapshot_t is not None and args.out is None:
        return

    out = Path(args.out) if args.out else default_out(event_lists)
    if out.suffix.lower() == ".mp4" and not shutil.which("ffmpeg"):
        out = out.with_suffix(".gif")
        print("ffmpeg not on PATH: writing a GIF instead")
    info = render_animation(event_lists, args.labels, graph, out, step=args.step,
                            fps=args.fps, start=start, end=end, dpi=args.dpi, **common)
    print(f"saved {out} ({out.stat().st_size / 1e6:.1f} MB): {info['frames']} frames in "
          f"{info['seconds']:.1f} s, {info['seconds_per_frame']:.3f} s/frame "
          f"(compute {info['compute_seconds']:.1f} s, draw+encode {info['grab_seconds']:.1f} s)")


if __name__ == "__main__":
    main()
