"""Replay a simulator JSONL log on the Secunderabad road map (R2, Week 4).

Run from the repo root:
    python -m src.viz.replay --log logs/viz_demo.jsonl --config configs/viz_demo.yaml
    python -m src.viz.replay --log logs/viz_demo.jsonl --config configs/viz_demo.yaml \
        --snapshot-t 07:00 --png docs/replay_example.png

Logic and drawing are kept apart so the Week 5 three-pane view can reuse them:
- load_log(path)                     -> list of event dicts (validated)
- state_at(events, t, config, graph) -> ReplayState (plain data, no matplotlib)
- ReplayRenderer(ax, graph, ...)     -> draws the base map once, then update(state)
See docs/replay_viz.md for the rules and the known gaps in the log.
"""
import argparse
import json
import math
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

REQUIRED_KEYS = ("run_id", "mode", "seed", "scenario", "rate", "t", "agent_id", "event", "payload")
BLOCKED_WINDOW_S = 60.0     # a vehicle counts as waiting this long after a blocked_wait
MAJOR_CLASSES = {"motorway", "trunk", "primary", "secondary"}
DEFAULT_STEP_S = 30.0
DEFAULT_FPS = 15
MAX_FRAMES_HINT = 600
OUT_DIR = Path("reports") / "replay"

COLORS = {
    "driving": "#1f77b4",       # blue
    "waiting": "#d62728",       # red
    "stationary": "#7f7f7f",    # grey
    "road": "#c8c8c8",
    "road_major": "#a8a8a8",
    "closure": "#d62728",
    "delivered": "#2ca02c",
    "failed": "#d62728",
    "open": "#222222",
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class LogFormatError(ValueError):
    """A line of the JSONL log is not valid (bad JSON or a missing key)."""


def load_log(path) -> List[Dict[str, Any]]:
    """Read a simulator JSONL log; every line must be JSON with all nine schema keys."""
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as e:
                raise LogFormatError(f"{path}, line {line_no}: bad JSON ({e.msg})") from e
            if not isinstance(event, dict):
                raise LogFormatError(f"{path}, line {line_no}: expected a JSON object")
            missing = [k for k in REQUIRED_KEYS if k not in event]
            if missing:
                raise LogFormatError(
                    f"{path}, line {line_no}: missing key(s) {', '.join(missing)}"
                )
            if not isinstance(event["payload"], dict):
                raise LogFormatError(f"{path}, line {line_no}: payload is not an object")
            events.append(event)
    return events


def load_config(path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# State at time t (plain data, no matplotlib)
# ---------------------------------------------------------------------------

@dataclass
class VehicleState:
    id: str
    state: str                          # driving / waiting / stationary
    node: Optional[int] = None          # node it is at (None while driving)
    edge: Optional[Tuple[int, int]] = None   # (u, v) while driving
    fraction: float = 0.0               # how far along the edge, 0..1
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class OrderState:
    id: str
    node: Optional[int]                 # None = location unknown (not drawn)
    state: str                          # not_released / open / delivered / failed
    dynamic: bool = False               # came from a new_order event
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class ReplayState:
    t: float
    vehicles: Dict[str, VehicleState] = field(default_factory=dict)
    orders: Dict[str, OrderState] = field(default_factory=dict)
    closures: List[Tuple[int, int, int]] = field(default_factory=list)
    spikes: List[Tuple[Tuple[int, int, int], float]] = field(default_factory=list)
    counters: Dict[str, int] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)


def _node_latlon(graph, node):
    if graph is None or node is None or node not in graph:
        return None, None
    data = graph.nodes[node]
    return float(data["lat"]), float(data["lon"])


def _vehicle_starts(config) -> Dict[str, int]:
    starts = {}
    for v in (config or {}).get("vehicles", []) or []:
        node = v.get("current_node", v.get("depot_node"))
        if node is not None:
            starts[str(v["id"])] = int(node)
    return starts


def state_at(events, t: float, config: Optional[dict] = None, graph=None) -> ReplayState:
    """What the world looks like at absolute time t (seconds from midnight).

    Only events with event.t <= t are used. graph (with node lat/lon) is optional:
    without it positions are given as nodes/edges only and lat/lon stay None.
    """
    state = ReplayState(t=float(t))
    if events:
        first = events[0]
        state.meta = {k: first[k] for k in ("run_id", "mode", "seed", "scenario", "rate")}

    # Per-vehicle running record: start node, last edge_enter, last exit, last wait.
    track: Dict[str, Dict[str, Any]] = {
        vid: {"node": node, "enter": None, "wait_t": None}
        for vid, node in _vehicle_starts(config).items()
    }
    orders: Dict[str, OrderState] = {}
    for o in (config or {}).get("orders", []) or []:
        release = float(o.get("release_time", 0.0))
        orders[str(o["id"])] = OrderState(
            id=str(o["id"]), node=int(o["node"]),
            state="not_released" if t < release else "open",
        )
    closures_total = spikes_total = skipped = new_orders = 0
    delivered = failed = 0
    closures, spikes = [], []

    for e in events:
        et = float(e["t"])
        if et > t:
            continue
        name, p, agent = e["event"], e["payload"], str(e["agent_id"])
        if name == "edge_enter":
            u, v = int(p["edge"][0]), int(p["edge"][1])
            rec = track.setdefault(agent, {"node": u, "enter": None, "wait_t": None})
            rec["enter"] = (et, u, v, float(p.get("expected_duration", 0.0)))
            rec["wait_t"] = None              # an edge_enter ends any waiting
        elif name == "edge_exit":
            rec = track.setdefault(agent, {"node": None, "enter": None, "wait_t": None})
            rec["node"], rec["enter"] = int(p["node"]), None
        elif name == "blocked_wait":
            rec = track.setdefault(agent, {"node": None, "enter": None, "wait_t": None})
            if rec["node"] is None and rec["enter"] is None:
                rec["node"] = int(p["edge"][0])   # it waits at the start of the edge
            rec["wait_t"] = et
        elif name == "disruption":
            edge = tuple(int(x) for x in p["edge"])
            active = et <= t < float(p["expiry"])
            if p.get("type") == "closure":
                closures_total += 1
                if active:
                    closures.append(edge)
            else:
                spikes_total += 1
                if active:
                    spikes.append((edge, float(p.get("magnitude") or 1.0)))
        elif name == "closure_skipped":
            skipped += 1
        elif name == "new_order":
            new_orders += 1
            oid = str(p.get("order_id", f"dyn_{new_orders}"))
            node = p.get("node")              # the sim does not log one yet (gap)
            orders.setdefault(oid, OrderState(
                id=oid, node=int(node) if node is not None else None,
                state="open", dynamic=True,
            ))
        elif name in ("order_delivered", "order_failed"):
            oid = str(p["order_id"])
            node = p.get("node")
            o = orders.setdefault(oid, OrderState(
                id=oid, node=int(node) if node is not None else None, state="open",
            ))
            if o.node is None and node is not None:
                o.node = int(node)
            if name == "order_delivered":
                o.state = "delivered"
                delivered += 1
            else:
                o.state = "failed"
                failed += 1

    for vid, rec in track.items():
        enter = rec["enter"]
        if enter is not None:
            t0, u, v, dur = enter
            if dur > 0 and math.isfinite(dur):
                frac = min(max((t - t0) / dur, 0.0), 1.0)
            else:
                frac = 1.0                    # zero/unknown duration: already at v
            vs = VehicleState(id=vid, state="driving", edge=(u, v), fraction=frac)
            (lat_u, lon_u), (lat_v, lon_v) = _node_latlon(graph, u), _node_latlon(graph, v)
            if lat_u is not None and lat_v is not None:
                vs.lat = lat_u + frac * (lat_v - lat_u)
                vs.lon = lon_u + frac * (lon_v - lon_u)
        elif rec["node"] is not None:
            waiting = rec["wait_t"] is not None and t - rec["wait_t"] <= BLOCKED_WINDOW_S
            vs = VehicleState(id=vid, state="waiting" if waiting else "stationary",
                              node=rec["node"])
            vs.lat, vs.lon = _node_latlon(graph, rec["node"])
        else:
            continue                          # nothing known yet: not shown
        state.vehicles[vid] = vs

    for o in orders.values():
        o.lat, o.lon = _node_latlon(graph, o.node)
    state.orders = orders
    state.closures, state.spikes = closures, spikes
    state.counters = {
        "delivered": delivered,
        "failed": failed,
        "total_orders": len(orders),
        "new_orders": new_orders,
        "undrawn_orders": sum(1 for o in orders.values() if o.node is None),
        "closures_active": len(closures),
        "closures_total": closures_total,
        "spikes_active": len(spikes),
        "spikes_total": spikes_total,
        "closure_skipped": skipped,
    }
    return state


def time_range(events) -> Tuple[float, float]:
    """(start, end) of the run: sim_start/sim_complete if logged, else first/last t."""
    if not events:
        raise ValueError("log has no events")
    start = min(float(e["t"]) for e in events)
    end = max(float(e["t"]) for e in events)
    for e in events:
        if e["event"] == "sim_start":
            p = e["payload"]
            start = float(p.get("start_time_s", e["t"]))
            if "duration_seconds" in p:
                end = max(end, start + float(p["duration_seconds"]))
    return start, end


def format_clock(t: float) -> str:
    """Seconds from midnight -> HH:MM."""
    minutes = int(t // 60)
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"


def parse_time(text: str) -> float:
    """'HH:MM', 'HH:MM:SS' or plain seconds from midnight -> seconds."""
    if ":" in text:
        parts = [float(x) for x in text.split(":")]
        while len(parts) < 3:
            parts.append(0.0)
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return float(text)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _road_class(data) -> str:
    if "road_class" in data:
        return str(data["road_class"])
    hw = data.get("highway", "")
    if isinstance(hw, list):
        hw = hw[0] if hw else ""
    return str(hw).removesuffix("_link")


class ReplayRenderer:
    """Draws the base map once, then moves only the dynamic artists per frame."""

    def __init__(self, ax, graph, spike_max: float = 3.0, show_legend: bool = True):
        from matplotlib.collections import LineCollection
        from matplotlib.colors import Normalize
        from matplotlib.transforms import offset_copy

        self.ax, self.G = ax, graph
        self.norm = Normalize(vmin=1.0, vmax=max(spike_max, 1.01))
        self.cmap = _spike_cmap()

        minor, major = [], []
        for u, v, data in graph.edges(data=True):
            seg = [self._xy(u), self._xy(v)]
            (major if _road_class(data) in MAJOR_CLASSES else minor).append(seg)
        ax.add_collection(LineCollection(minor, colors=COLORS["road"], linewidths=0.6, zorder=1))
        ax.add_collection(LineCollection(major, colors=COLORS["road_major"], linewidths=1.8,
                                         zorder=1))

        lons = [d["lon"] for _, d in graph.nodes(data=True)]
        lats = [d["lat"] for _, d in graph.nodes(data=True)]
        pad_x = (max(lons) - min(lons)) * 0.03 or 0.001
        pad_y = (max(lats) - min(lats)) * 0.03 or 0.001
        ax.set_xlim(min(lons) - pad_x, max(lons) + pad_x)
        ax.set_ylim(min(lats) - pad_y, max(lats) + pad_y)
        mid_lat = (min(lats) + max(lats)) / 2
        ax.set_aspect(1.0 / math.cos(math.radians(mid_lat)))  # 1 deg lon is shorter
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#dddddd")

        # Dynamic artists (empty until the first update).
        self.spike_lines = LineCollection([], cmap=self.cmap, norm=self.norm,
                                          linewidths=5, zorder=3)
        ax.add_collection(self.spike_lines)
        self.closure_lines = LineCollection([], colors=COLORS["closure"], linewidths=5,
                                            zorder=4)
        ax.add_collection(self.closure_lines)
        # Closed edges are short (~50-150 m), so ring them to keep them visible.
        self.closure_rings = ax.scatter([], [], s=260, facecolors="none",
                                        edgecolors=COLORS["closure"], linewidths=2, zorder=4)
        self.open_orders = ax.scatter([], [], s=55, facecolors="none",
                                      edgecolors=COLORS["open"], linewidths=1.3, zorder=5)
        self.done_orders = ax.scatter([], [], s=55, c=COLORS["delivered"],
                                      edgecolors="white", linewidths=0.6, zorder=5)
        self.failed_orders = ax.scatter([], [], s=70, c=COLORS["failed"], marker="x",
                                        linewidths=2, zorder=5)
        self.vehicles = ax.scatter([], [], s=95, edgecolors="white", linewidths=1, zorder=7)
        self.labels: List[Any] = []
        # Labels sit a few points up-right of their dot, whatever the zoom.
        self._label_offset = offset_copy(ax.transData, fig=ax.figure, x=4, y=4, units="points")
        # HUD sits just above the map and the legend just below it, so neither
        # ever hides a vehicle, order or closure.
        self.hud = ax.text(
            0.0, 1.01, "", transform=ax.transAxes, va="bottom", ha="left", fontsize=8.5,
            family="monospace", zorder=10, clip_on=False,
        )
        if show_legend:
            self._legend()

    def _xy(self, node):
        d = self.G.nodes[node]
        return (float(d["lon"]), float(d["lat"]))

    def _legend(self):
        from matplotlib.lines import Line2D

        handles = [
            Line2D([], [], marker="o", ls="", color=COLORS["driving"], label="vehicle driving"),
            Line2D([], [], marker="o", ls="", color=COLORS["waiting"], label="vehicle waiting"),
            Line2D([], [], marker="o", ls="", color=COLORS["stationary"],
                   label="vehicle stationary"),
            Line2D([], [], marker="o", ls="", mfc="none", color=COLORS["open"],
                   label="order open"),
            Line2D([], [], marker="o", ls="", color=COLORS["delivered"], label="order delivered"),
            Line2D([], [], marker="x", ls="", color=COLORS["failed"], mew=2,
                   label="order failed"),
            Line2D([], [], color=COLORS["closure"], lw=4, label="road closed"),
            Line2D([], [], color=self.cmap(0.75), lw=5, label="traffic spike (yellow to red)"),
        ]
        self.ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.01),
                       ncol=4, fontsize=7.5, frameon=False, columnspacing=1.2,
                       handlelength=1.8)

    @staticmethod
    def _offsets(points):
        import numpy as np
        return np.array(points, dtype=float).reshape(-1, 2)

    def update(self, state: ReplayState) -> List[Any]:
        """Move the dynamic artists to `state`; returns them (for blitting)."""
        # Roads
        self.closure_lines.set_segments([[self._xy(u), self._xy(v)]
                                         for u, v, _ in state.closures if u in self.G
                                         and v in self.G])
        mids = [((self._xy(u)[0] + self._xy(v)[0]) / 2, (self._xy(u)[1] + self._xy(v)[1]) / 2)
                for u, v, _ in state.closures if u in self.G and v in self.G]
        self.closure_rings.set_offsets(self._offsets(mids))
        spikes = [(e, m) for e, m in state.spikes if e[0] in self.G and e[1] in self.G]
        self.spike_lines.set_segments([[self._xy(e[0]), self._xy(e[1])] for e, _ in spikes])
        self.spike_lines.set_array([m for _, m in spikes])

        # Orders (not_released and node-less ones are not drawn)
        by_state = {"open": [], "delivered": [], "failed": []}
        for o in state.orders.values():
            if o.lat is not None and o.state in by_state:
                by_state[o.state].append((o.lon, o.lat))
        self.open_orders.set_offsets(self._offsets(by_state["open"]))
        self.done_orders.set_offsets(self._offsets(by_state["delivered"]))
        self.failed_orders.set_offsets(self._offsets(by_state["failed"]))

        # Vehicles: one dot each; vehicles on the same spot share one label.
        shown = [v for v in sorted(state.vehicles.values(), key=lambda v: _vid_key(v.id))
                 if v.lat is not None]
        self.vehicles.set_offsets(self._offsets([(v.lon, v.lat) for v in shown]))
        self.vehicles.set_color([COLORS[v.state] for v in shown])
        self.vehicles.set_edgecolor("white")
        groups: Dict[Tuple[float, float], List[str]] = {}
        for v in shown:
            groups.setdefault((round(v.lon, 4), round(v.lat, 4)), []).append(v.id)
        while len(self.labels) < len(groups):
            self.labels.append(self.ax.text(
                0, 0, "", fontsize=7, color="#111111", zorder=8, ha="left", va="bottom",
                transform=self._label_offset,
                bbox=dict(boxstyle="round,pad=0.12", facecolor="white", edgecolor="none",
                          alpha=0.75),
            ))
        for label, ((lon, lat), ids) in zip(self.labels, sorted(groups.items())):
            label.set_text(",".join(ids))
            label.set_position((lon, lat))
            label.set_visible(True)
        for label in self.labels[len(groups):]:
            label.set_visible(False)

        self.hud.set_text(hud_text(state))
        return [self.closure_lines, self.closure_rings, self.spike_lines, self.open_orders,
                self.done_orders, self.failed_orders, self.vehicles, self.hud, *self.labels]


def _vid_key(vid: str):
    digits = "".join(ch for ch in vid if ch.isdigit())
    return (vid.rstrip("0123456789"), int(digits) if digits else 0, vid)


def _spike_cmap():
    from matplotlib import colormaps
    from matplotlib.colors import LinearSegmentedColormap
    base = colormaps["YlOrRd"]
    # Skip the palest yellows so a weak spike is still visible on a white map.
    return LinearSegmentedColormap.from_list("spike", [base(x) for x in (0.3, 0.55, 0.8, 1.0)])


def hud_text(state: ReplayState) -> str:
    c, m = state.counters, state.meta
    rate = m.get("rate")
    rate_txt = f"{float(rate):g}/h" if rate is not None else "n/a"
    lines = [
        f"{format_clock(state.t)}   replay of {m.get('run_id', '')}, Secunderabad road map",
        f"mode: {m.get('mode', 'n/a')}   disruption rate: {rate_txt}",
        f"orders: {c.get('delivered', 0)} delivered / {c.get('failed', 0)} failed"
        f" / {c.get('total_orders', 0)} total",
    ]
    if c.get("new_orders"):
        lines.append(f"  dynamic: {c['new_orders']} ({c.get('undrawn_orders', 0)} no location)")
    lines += [
        f"closures: {c.get('closures_active', 0)} active / {c.get('closures_total', 0)} so far"
        f"   (skipped {c.get('closure_skipped', 0)})",
        f"spikes:   {c.get('spikes_active', 0)} active / {c.get('spikes_total', 0)} so far",
        # TODO(R5/R8): show agent messages once the log has message events.
        "messages: n/a",
    ]
    return "\n".join(lines)


def spike_max_from(events, config=None) -> float:
    vals = [3.0]
    params = (config or {}).get("disruptions") or {}
    if "max_spike" in params:
        vals.append(float(params["max_spike"]))
    vals += [float(e["payload"].get("magnitude") or 1.0) for e in events
             if e["event"] == "disruption" and e["payload"].get("type") != "closure"]
    return max(vals)


def make_figure(graph, events, config=None, figsize=(8, 9.8)):
    """One map pane with room for the HUD above and the legend below."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=figsize)
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.07, top=0.85)
    renderer = ReplayRenderer(ax, graph, spike_max=spike_max_from(events, config))
    return fig, ax, renderer


def frame_times(start: float, end: float, step: float) -> List[float]:
    if step <= 0:
        raise ValueError("step must be positive")
    n = int(math.floor((end - start) / step)) + 1
    return [start + i * step for i in range(max(n, 1))]


def render_animation(events, graph, out_path, config=None, step=DEFAULT_STEP_S,
                     fps=DEFAULT_FPS, start=None, end=None, dpi=80) -> Dict[str, float]:
    """Render frames to an .mp4 (ffmpeg) or .gif (Pillow). Returns timing info."""
    import matplotlib.pyplot as plt
    from matplotlib.animation import FFMpegWriter, PillowWriter

    run_start, run_end = time_range(events)
    times = frame_times(run_start if start is None else start,
                        run_end if end is None else end, step)
    if len(times) > MAX_FRAMES_HINT:
        print(f"note: {len(times)} frames (> {MAX_FRAMES_HINT}); use a larger --step to cut it")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".mp4":
        writer = FFMpegWriter(fps=fps)
    else:
        writer = PillowWriter(fps=fps)

    t0 = time.perf_counter()
    fig, _, renderer = make_figure(graph, events, config)
    with writer.saving(fig, str(out_path), dpi=dpi):
        for t in times:
            renderer.update(state_at(events, t, config, graph))
            writer.grab_frame()
    plt.close(fig)
    elapsed = time.perf_counter() - t0
    return {"frames": len(times), "seconds": elapsed, "seconds_per_frame": elapsed / len(times)}


def render_snapshot(events, graph, t, png_path, config=None, dpi=100):
    import matplotlib.pyplot as plt
    fig, _, renderer = make_figure(graph, events, config)
    state = state_at(events, t, config, graph)
    renderer.update(state)
    Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=dpi, facecolor="white")
    plt.close(fig)
    return state


def default_out(run_id: str) -> Path:
    ext = ".mp4" if shutil.which("ffmpeg") else ".gif"
    return OUT_DIR / f"{run_id}{ext}"


def load_graph_for(config) -> Any:
    from src.world.graph_loader import load_road_graph
    map_path = (config or {}).get("map_path", "data/processed/secunderabad.graphml")
    return load_road_graph(Path(map_path).stem)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Replay a simulator JSONL log on the map.")
    parser.add_argument("--log", required=True, help="simulator JSONL log")
    parser.add_argument("--config", help="sim config YAML (depots and order locations)")
    parser.add_argument("--out", help="video path (.mp4 needs ffmpeg, else .gif)")
    parser.add_argument("--step", type=float, default=DEFAULT_STEP_S,
                        help="sim seconds per frame (default 30)")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--dpi", type=int, default=80, help="video resolution (default 80)")
    parser.add_argument("--start", help="first frame time, HH:MM or seconds from midnight")
    parser.add_argument("--end", help="last frame time, HH:MM or seconds from midnight")
    parser.add_argument("--snapshot-t", help="also save one frame at this time (HH:MM or s)")
    parser.add_argument("--png", help="snapshot path (default reports/replay/<run_id>.png)")
    parser.add_argument("--show", action="store_true", help="open a window (live playback)")
    args = parser.parse_args(argv)

    import matplotlib
    if not args.show:
        matplotlib.use("Agg")

    events = load_log(args.log)
    if not events:
        raise SystemExit(f"{args.log}: log is empty")
    config = load_config(args.config) if args.config else None
    run_id = events[0]["run_id"]
    graph = load_graph_for(config)
    start = parse_time(args.start) if args.start else None
    end = parse_time(args.end) if args.end else None

    snapshot_only = args.snapshot_t is not None and args.out is None and not args.show
    if args.snapshot_t is not None:
        png = Path(args.png) if args.png else OUT_DIR / f"{run_id}.png"
        t = parse_time(args.snapshot_t)
        t0 = time.perf_counter()
        state = render_snapshot(events, graph, t, png, config)
        print(f"snapshot {format_clock(t)} -> {png} "
              f"({png.stat().st_size / 1024:.0f} KB, {time.perf_counter() - t0:.2f} s); "
              f"closures active {state.counters['closures_active']}, "
              f"spikes active {state.counters['spikes_active']}")
    if args.show:
        _show(events, graph, config, args.step, start, end, args.fps)
        return
    if snapshot_only:
        return

    out = Path(args.out) if args.out else default_out(run_id)
    if out.suffix.lower() == ".mp4" and not shutil.which("ffmpeg"):
        out = out.with_suffix(".gif")
        print("ffmpeg not on PATH: writing a GIF instead")
    info = render_animation(events, graph, out, config, step=args.step, fps=args.fps,
                            start=start, end=end, dpi=args.dpi)
    print(f"saved {out} ({out.stat().st_size / 1e6:.1f} MB): {info['frames']} frames in "
          f"{info['seconds']:.1f} s, {info['seconds_per_frame']:.3f} s/frame")


def _show(events, graph, config, step, start, end, fps):
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    run_start, run_end = time_range(events)
    times = frame_times(run_start if start is None else start,
                        run_end if end is None else end, step)
    fig, _, renderer = make_figure(graph, events, config)
    anim = FuncAnimation(fig, lambda t: renderer.update(state_at(events, t, config, graph)),
                         frames=times, interval=1000 / fps, blit=False, repeat=False)
    plt.show()
    return anim


if __name__ == "__main__":
    main()
