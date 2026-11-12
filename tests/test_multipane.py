"""Tests for the Week 5 side-by-side replay (src/viz/multipane.py).

Headless (Agg), hand-made logs in tmp_path, a 5-node graph: no map, no committed logs.
"""
import json

import matplotlib
import networkx as nx
import pytest

matplotlib.use("Agg")

from src.viz import multipane  # noqa: E402
from src.viz.multipane import (FLASH_S, LogMismatchError, Player, check_same_run,  # noqa: E402
                               flashes_at, message_counts_at, pane_counters)
from src.viz.replay import state_at  # noqa: E402

START = 21600.0


def small_graph():
    G = nx.MultiDiGraph()
    coords = {1: (17.430, 78.490), 2: (17.430, 78.500), 3: (17.440, 78.500),
              4: (17.440, 78.490), 5: (17.435, 78.495)}
    for n, (lat, lon) in coords.items():
        G.add_node(n, lat=lat, lon=lon, x=lon, y=lat)
    for u, v in [(1, 2), (2, 3), (3, 4), (4, 1), (1, 5), (5, 3)]:
        G.add_edge(u, v, 0, highway="residential", length=1000.0)
        G.add_edge(v, u, 0, highway="residential", length=1000.0)
    return G


def ev(t, event, payload, agent="env", seed=1, scenario="unit", mode="independent"):
    return {"run_id": f"run_{mode}", "mode": mode, "seed": seed, "scenario": scenario,
            "rate": 5.0, "t": float(START + t), "agent_id": agent, "event": event,
            "payload": payload}


CONFIG = {
    "start_time_s": START, "duration_seconds": 600.0,
    "vehicles": [{"id": "V1", "depot_node": 1, "capacity": 100},
                 {"id": "V2", "depot_node": 4, "capacity": 100}],
    "orders": [{"id": "O1", "node": 2, "demand": 5, "release_time": 0.0}],
}


def base_log(mode="independent", **kw):
    return [
        ev(0, "sim_start", {"start_time_s": START, "duration_seconds": 600.0,
                            "n_vehicles": 2, "n_orders": 1}, mode=mode, **kw),
        ev(0, "edge_enter", {"edge": [1, 2, 0], "expected_duration": 100.0}, "V1",
           mode=mode, **kw),
        ev(100, "edge_exit", {"node": 2}, "V1", mode=mode, **kw),
        ev(100, "order_delivered", {"order_id": "O1", "node": 2, "demand": 5}, "V1",
           mode=mode, **kw),
    ]


def write_log(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


# --- message counts -------------------------------------------------------

def test_message_counts_known_numbers_and_count_payload():
    log = base_log() + [
        ev(10, "allocation", {}),
        ev(20, "negotiation_request", {"count": 3}),
        ev(25, "negotiation_response", {"count": 2}),
        ev(30, "negotiation_result", {}),
        ev(31, "negotiation_result", {"count": 4}),
        ev(500, "negotiation_request", {"count": 10}),       # after t: ignored
    ]
    c = message_counts_at(log, START + 100)
    assert c == {"allocation": 1, "negotiation_request": 3, "negotiation_response": 2,
                 "negotiation_result": 5, "total": 11}
    assert message_counts_at(log, START + 500)["negotiation_request"] == 13
    # before any message row the log still logs messages, so 0 (not n/a) is true
    assert message_counts_at(log, START + 5)["total"] == 0


def test_message_counts_none_when_not_logged():
    assert message_counts_at(base_log(), START + 1000) is None
    frame = multipane.compute_pane(base_log(), START + 50, CONFIG, small_graph())
    assert "messages: n/a (not logged)" in multipane.pane_hud_text("A", frame)


# --- negotiation flashes ---------------------------------------------------

def test_flash_at_edge_midpoint():
    G = small_graph()
    log = base_log() + [ev(200, "negotiation_result", {"edge": [1, 2, 0], "vehicles": ["V1"]})]
    t = START + 210
    f = flashes_at(log, t, state_at(log, t, CONFIG, G), G)
    assert (f.active, f.undrawn) == (1, 0)
    assert f.points == [pytest.approx((78.495, 17.430))]   # edge wins over vehicles


def test_flash_at_vehicles_when_no_edge():
    G = small_graph()
    log = base_log() + [ev(200, "negotiation_result", {"vehicles": ["V1", "V2", "V9"]})]
    t = START + 210
    f = flashes_at(log, t, state_at(log, t, CONFIG, G), G)
    # V1 at node 2, V2 at its depot node 4; V9 is unknown and skipped
    assert sorted(f.points) == sorted([(78.500, 17.430), (78.490, 17.440)])
    assert f.undrawn == 0


def test_flash_undrawn_when_no_position():
    G = small_graph()
    log = base_log() + [ev(200, "negotiation_result", {"edge": [77, 88]}),
                        ev(200, "negotiation_result", {"vehicles": ["V9"]}),
                        ev(200, "negotiation_result", {})]
    t = START + 210
    f = flashes_at(log, t, state_at(log, t, CONFIG, G), G)
    assert (f.active, f.undrawn, f.points) == (3, 3, [])


def test_flash_expires_after_60_s():
    G = small_graph()
    log = base_log() + [ev(200, "negotiation_result", {"edge": [1, 2]})]
    for dt, active in [(-1, 0), (0, 1), (FLASH_S - 0.01, 1), (FLASH_S, 0), (FLASH_S + 5, 0)]:
        t = START + 200 + dt
        assert flashes_at(log, t, state_at(log, t, CONFIG, G), G).active == active, dt


# --- seed / scenario check -------------------------------------------------

def test_mismatch_raises_unless_allowed():
    a, b = base_log(seed=1), base_log(seed=2)
    assert check_same_run([a, base_log(seed=1)], ["A", "B"]) == []
    with pytest.raises(LogMismatchError, match="seed"):
        check_same_run([a, b], ["A", "B"])
    with pytest.raises(LogMismatchError, match="scenario"):
        check_same_run([a, base_log(scenario="other")], ["A", "B"])
    warnings = check_same_run([a, b], ["A", "B"], allow_mismatch=True)
    assert len(warnings) == 1 and "NOT" in warnings[0]
    assert check_same_run([a, []], ["A", "empty"]) == []        # empty log: nothing to check


def test_cli_mismatch_stops_and_allow_mismatch_renders(tmp_path, monkeypatch):
    monkeypatch.setattr(multipane, "load_graph_for", lambda config: small_graph())
    cfg = tmp_path / "c.yaml"
    cfg.write_text(json.dumps(CONFIG), encoding="utf-8")       # JSON is valid YAML
    la = write_log(tmp_path / "a.jsonl", base_log(seed=1))
    lb = write_log(tmp_path / "b.jsonl", base_log(seed=2))
    png = tmp_path / "m.png"
    argv = ["--logs", str(la), str(lb), "--labels", "A", "B", "--config", str(cfg),
            "--snapshot-t", "06:02", "--png", str(png)]
    with pytest.raises(SystemExit, match="same scenario and seed"):
        multipane.main(argv)
    assert not png.exists()
    multipane.main(argv + ["--allow-mismatch"])
    assert png.stat().st_size > 0


# --- waits, replans, trigger ----------------------------------------------

def test_waits_replans_and_trigger_counters():
    log = base_log() + [
        ev(110, "blocked_wait", {"edge": [2, 3, 0]}, "V1"),
        ev(170, "blocked_wait", {"edge": [2, 3, 0]}, "V1"),
        ev(150, "replan", {"trigger": "closure"}, "V1"),
        ev(150, "replan", {"trigger": "closure"}, "V2"),
        ev(160, "trigger_toggle", {"trigger_enabled": True}),
        ev(300, "trigger_toggle", {"trigger_enabled": False}),
        ev(400, "replan", {"trigger": "traffic_spike"}, "V1"),
    ]
    assert pane_counters(log, START + 100) == {"waits": 0, "replans": 0, "trigger": None}
    assert pane_counters(log, START + 160) == {"waits": 1, "replans": 2, "trigger": True}
    assert pane_counters(log, START + 299) == {"waits": 2, "replans": 2, "trigger": True}
    assert pane_counters(log, START + 400) == {"waits": 2, "replans": 3, "trigger": False}


# --- playback state --------------------------------------------------------

def test_player_keys():
    p = Player(0.0, 100.0, 10.0)
    p.advance()
    assert p.t == 10.0
    p.key("+")
    p.advance()
    assert (p.speed, p.t) == (2.0, 30.0)
    p.key(" ")
    p.advance()
    assert p.paused and p.t == 30.0
    p.key("right")
    assert p.t == 50.0
    p.key("left")
    p.key("left")
    p.key("left")
    assert p.t == 0.0                       # clamped at the start
    for _ in range(20):
        p.key("-")
    assert p.speed == 0.25
    for _ in range(20):
        p.key("+")
    assert p.speed == 16.0
    p.key("r")
    assert (p.t, p.paused) == (0.0, False)
    p.advance()
    assert p.t == 100.0 and p.paused        # clamped at the end, then pauses


# --- rendering -------------------------------------------------------------

def _messages_log():
    return base_log(mode="full") + [
        ev(30, "negotiation_request", {"count": 2}, mode="full"),
        ev(40, "negotiation_result", {"edge": [1, 2, 0]}, mode="full"),
        ev(40, "trigger_toggle", {"trigger_enabled": True}, mode="full"),
    ]


def test_three_pane_snapshot(tmp_path):
    png = tmp_path / "three.png"
    logs = [base_log("no_replanning"), base_log("independent"), _messages_log()]
    mp = multipane.render_snapshot(logs, ["none", "independent", "full"], small_graph(),
                                   START + 50, png, CONFIG)
    assert png.stat().st_size > 0
    huds = [v.hud.get_text() for v in mp.views]
    assert "messages: n/a (not logged)" in huds[0]
    assert "messages: 3 (alloc 0, req 2, resp 0, result 1)" in huds[2]
    assert "negotiation flashes: 1 active, 0 not drawn" in huds[2]
    assert "trigger: on" in huds[2]
    assert len(mp.views[2].flash.get_offsets()) == 1
    assert [v.renderer.ax.get_legend() is not None for v in mp.views] == [True, False, False]


def test_two_pane_snapshot_column_layout(tmp_path):
    png = tmp_path / "two.png"
    mp = multipane.render_snapshot([base_log(), base_log()], ["A", "B"], small_graph(),
                                   START + 50, png, CONFIG, layout="column")
    assert png.stat().st_size > 0 and len(mp.views) == 2


def test_empty_and_short_log_panes_do_not_crash(tmp_path):
    png = tmp_path / "empty.png"
    short = base_log()[:2]
    normal = base_log() + [
        ev(200, "edge_enter", {"edge": [2, 3, 0], "expected_duration": 50.0}, "V1")]
    mp = multipane.render_snapshot([normal, [], short], ["full", "empty", "short"],
                                   small_graph(), START + 50, png, CONFIG)
    assert png.stat().st_size > 0
    assert mp.views[1].note.get_visible() and "empty" in mp.views[1].note.get_text()
    assert mp.views[2].note.get_visible() and "short" in mp.views[2].note.get_text()
    assert not mp.views[0].note.get_visible()


def test_all_empty_logs_use_config_clock(tmp_path):
    assert multipane.shared_range([[], []], CONFIG) == (START, START + 600.0)
    info = multipane.render_animation([[], []], ["a", "b"], small_graph(),
                                      tmp_path / "e.gif", CONFIG, step=300)
    assert info["frames"] == 3


def test_short_animation_writes_gif(tmp_path):
    out = tmp_path / "a.gif"
    info = multipane.render_animation([base_log(), _messages_log()], ["A", "B"],
                                      small_graph(), out, CONFIG, step=200, dpi=40)
    assert out.stat().st_size > 0 and info["frames"] == 4
    assert info["compute_seconds"] >= 0 and info["grab_seconds"] > 0


def test_wrong_number_of_logs_or_labels():
    with pytest.raises(ValueError):
        multipane.MultiPane(small_graph(), [base_log()], ["A"], CONFIG)
    with pytest.raises(ValueError):
        multipane.MultiPane(small_graph(), [base_log(), base_log()], ["A"], CONFIG)


# --- Week 6: pre-rendered roads, layout, snapshots ---------------------------

def _rgba(fig, dpi):
    import io

    import numpy as np
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
    buf.seek(0)
    return (matplotlib.pyplot.imread(buf, format="png") * 255).round().astype(np.int16)


def test_prerender_gives_the_same_pixels_and_keeps_limits():
    import numpy as np
    G, log = small_graph(), base_log()
    out = {}
    for pre in (False, True):
        mp = multipane.MultiPane(G, [log, log], ["A", "B"], CONFIG)
        r = mp.views[0].renderer
        limits = (r.ax.get_xlim(), r.ax.get_ylim(), r.ax.get_aspect())
        if pre:
            assert mp.prerender(80) is True
            assert r.road_image is not None
            assert not any(c.get_visible() for c in r.road_collections)
            assert (r.ax.get_xlim(), r.ax.get_ylim(), r.ax.get_aspect()) == limits
        mp.update(START + 50)
        out[pre] = _rgba(mp.fig, 80)
        matplotlib.pyplot.close(mp.fig)
    assert out[False].shape == out[True].shape
    assert int(np.abs(out[False] - out[True]).max()) <= 1      # measured: 0-1 of 255


def test_prerender_redone_only_when_pixel_size_changes():
    mp = multipane.MultiPane(small_graph(), [base_log(), base_log()], ["A", "B"], CONFIG)
    assert mp.prerender(80) is True
    assert mp.prerender(80) is False                  # nothing changed: kept
    assert mp.prerender(100) is True                  # another dpi
    w, h = mp.fig.get_size_inches()
    mp.fig.set_size_inches(w + 1, h)                  # a resized window
    assert mp.prerender(100) is True
    mp.clear_prerender()
    assert all(c.get_visible() for c in mp.views[0].renderer.road_collections)
    matplotlib.pyplot.close(mp.fig)


@pytest.mark.parametrize("warnings", [(), ("logs are NOT from the same scenario and seed",)])
def test_row_layout_hud_fits_between_clock_and_map(warnings):
    log = _messages_log()
    mp = multipane.MultiPane(small_graph(), [log, log, log], ["A", "B", "C"], CONFIG,
                             warnings=warnings)
    mp.update(START + 5000)                            # after the log: longest HUD, 9 lines
    fig = mp.fig
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    top_box = (mp.warning or mp.clock).get_window_extent(rend)
    for v in mp.views:
        hud = v.hud.get_window_extent(rend)
        assert len(v.hud.get_text().splitlines()) == 9
        assert hud.y1 <= top_box.y0                    # HUD below the clock / banner
    legend = mp.views[0].ax.get_legend().get_window_extent(rend)
    assert legend.y0 >= 0                              # legend inside the figure
    matplotlib.pyplot.close(fig)


def test_snapshot_times_writes_one_png_per_time(tmp_path, monkeypatch):
    monkeypatch.setattr(multipane, "load_graph_for", lambda config: small_graph())
    cfg = tmp_path / "c.yaml"
    cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
    la = write_log(tmp_path / "a.jsonl", base_log())
    base = tmp_path / "snap.png"
    multipane.main(["--logs", str(la), str(la), "--labels", "A", "B", "--config", str(cfg),
                    "--snapshot-times", "06:01", "06:02", "06:05", "--png", str(base)])
    for hhmm in ("0601", "0602", "0605"):
        assert (tmp_path / f"snap_{hhmm}.png").stat().st_size > 0
    assert not base.exists()


# --- Week 6: edge cases ------------------------------------------------------

def _cli(tmp_path, monkeypatch, logs, extra=(), config=CONFIG, graph=None):
    """Run the CLI on hand-made logs (lists of rows, or a str for raw file text)."""
    monkeypatch.setattr(multipane, "load_graph_for", lambda cfg: graph or small_graph())
    paths = []
    for i, rows in enumerate(logs):
        p = tmp_path / f"log{i}.jsonl"
        if isinstance(rows, str):
            p.write_text(rows, encoding="utf-8")
        else:
            write_log(p, rows)
        paths.append(str(p))
    argv = ["--logs", *paths, "--labels", *[f"L{i}" for i in range(len(logs))]]
    if config is not None:
        cfg = tmp_path / "c.yaml"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        argv += ["--config", str(cfg)]
    png = tmp_path / "out.png"
    multipane.main(argv + ["--png", str(png), *extra])
    return png


def test_edge_empty_log_file(tmp_path, monkeypatch):
    png = _cli(tmp_path, monkeypatch, [base_log(), ""], ["--snapshot-t", "06:01"])
    assert png.stat().st_size > 0


def test_edge_log_with_only_start_and_complete(tmp_path, monkeypatch):
    rows = [base_log()[0], ev(600, "sim_complete", {})]
    png = _cli(tmp_path, monkeypatch, [rows, base_log()], ["--snapshot-t", "06:05"])
    assert png.stat().st_size > 0
    mp = multipane.MultiPane(small_graph(), [rows, base_log()], ["A", "B"], CONFIG)
    mp.update(START + 300)
    assert mp.views[0].note.get_visible() and "only 2 event" in mp.views[0].note.get_text()
    st = mp.views[0].compute(START + 300).state
    states = {v.id: v.state for v in st.vehicles.values()}
    assert states == {"V1": "stationary", "V2": "stationary"}
    matplotlib.pyplot.close(mp.fig)


def test_edge_pane_that_ends_early_holds_last_state_and_says_finished():
    short = [ev(0, "edge_enter", {"edge": [1, 2, 0], "expected_duration": 50.0}, "V1"),
             ev(50, "edge_exit", {"node": 2}, "V1"),
             ev(90, "blocked_wait", {"edge": [2, 3, 0]}, "V1"),
             ev(100, "sim_complete", {})]                 # no sim_start: ends at +100
    mp = multipane.MultiPane(small_graph(), [short, base_log()], ["short", "long"], CONFIG)
    assert multipane.shared_range([short, base_log()]) == (START, START + 600)
    mp.update(START + 300)
    assert "FINISHED: log ended at 06:01, last state held" in mp.views[0].hud.get_text()
    assert "FINISHED" not in mp.views[1].hud.get_text()
    frame = mp.views[0].compute(START + 300)
    assert frame.t == START + 300 and frame.state.t == START + 100
    # V1 was waiting when its log ended; without the hold it turns grey 60 s later.
    assert frame.state.vehicles["V1"].state == "waiting"
    matplotlib.pyplot.close(mp.fig)


def test_edge_start_after_end_or_outside_range(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="after --end"):
        multipane.check_times(START, START + 600, START + 300, START + 100)
    with pytest.raises(ValueError, match="outside the logs' time range"):
        multipane.check_times(START, START + 600, snapshots=[START + 601])
    multipane.check_times(START, START + 600, START, START + 600, [START + 600])   # edges ok
    with pytest.raises(SystemExit, match="after --end"):
        _cli(tmp_path, monkeypatch, [base_log(), base_log()],
             ["--start", "06:08", "--end", "06:02", "--out", str(tmp_path / "x.gif")])
    with pytest.raises(SystemExit, match="06:00-06:10"):
        _cli(tmp_path, monkeypatch, [base_log(), base_log()], ["--snapshot-t", "09:00"])
    with pytest.raises(SystemExit, match="outside"):
        _cli(tmp_path, monkeypatch, [base_log(), base_log()],
             ["--start", "05:00", "--out", str(tmp_path / "x.gif")])


def _grid_graph(k=20):
    G = nx.MultiDiGraph()
    for i in range(k):
        for j in range(k):
            G.add_node(i * k + j, lat=17.40 + 0.002 * i, lon=78.48 + 0.002 * j)
    for i in range(k):
        for j in range(k):
            n = i * k + j
            for m in ([n + 1] if j < k - 1 else []) + ([n + k] if i < k - 1 else []):
                G.add_edge(n, m, 0, highway="residential")
                G.add_edge(m, n, 0, highway="residential")
    return G


def test_edge_150_closures_and_150_spikes_at_once():
    import time as _time
    G = _grid_graph()
    rows = [base_log()[0]]
    for i, (u, v, k) in enumerate(list(G.edges(keys=True))[:300]):
        kind = {"type": "closure"} if i < 150 else {"type": "traffic_spike", "magnitude": 2.5}
        rows.append(ev(10, "disruption", {**kind, "edge": [u, v, k], "expiry": START + 500}))
    cfg = {**CONFIG, "vehicles": [], "orders": []}
    mp = multipane.MultiPane(G, [rows, rows], ["A", "B"], cfg)
    mp.prerender(80)
    t0 = _time.perf_counter()
    mp.update(START + 100)
    _rgba(mp.fig, 80)
    print(f"150 closures + 150 spikes, 2 panes: {_time.perf_counter() - t0:.3f} s/frame")
    assert "closures active: 150   spikes active: 150" in mp.views[0].hud.get_text()
    assert len(mp.views[0].renderer.closure_lines.get_segments()) == 150
    assert len(mp.views[0].renderer.spike_lines.get_segments()) == 150
    matplotlib.pyplot.close(mp.fig)


def test_edge_20_vehicles_on_one_node_label_wraps():
    cfg = {**CONFIG, "vehicles": [{"id": f"V{i}", "depot_node": 1, "capacity": 100}
                                  for i in range(1, 21)]}
    mp = multipane.MultiPane(small_graph(), [base_log()[:1]] * 2, ["A", "B"], cfg)
    mp.update(START + 1)
    labels = [lab for lab in mp.views[0].renderer.labels if lab.get_visible()]
    assert len(labels) == 1
    assert labels[0].get_text().splitlines() == [
        "V1,V2,V3,V4,V5", "V6,V7,V8,V9,V10", "V11,V12,V13,V14,V15", "V16,V17,V18,V19,V20"]
    matplotlib.pyplot.close(mp.fig)


def test_edge_config_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(multipane, "load_graph_for", lambda cfg: small_graph())
    la = write_log(tmp_path / "a.jsonl", base_log())
    with pytest.raises(SystemExit, match="config not found"):
        multipane.main(["--logs", str(la), str(la), "--labels", "A", "B",
                        "--config", str(tmp_path / "nope.yaml"), "--snapshot-t", "06:01"])
    png = _cli(tmp_path, monkeypatch, [base_log(), base_log()], ["--snapshot-t", "06:01"],
               config=None)
    assert png.stat().st_size > 0
    mp = multipane.MultiPane(small_graph(), [base_log(), base_log()], ["A", "B"], None)
    mp.update(START + 10)
    assert "config: none" in mp.views[0].hud.get_text()
    st = mp.views[0].compute(START + 10).state
    assert list(st.vehicles) == ["V1"]       # V2 never moves: unknown without a config
    matplotlib.pyplot.close(mp.fig)


def test_edge_bad_json_line_names_the_line(tmp_path, monkeypatch):
    text = "".join(json.dumps(r) + "\n" for r in base_log()[:2]) + "{not json\n"
    with pytest.raises(SystemExit, match="line 3: bad JSON"):
        _cli(tmp_path, monkeypatch, [base_log(), text], ["--snapshot-t", "06:01"])


@pytest.mark.parametrize("n", [1, 4])
def test_edge_one_or_four_logs_print_usage(tmp_path, monkeypatch, capsys, n):
    with pytest.raises(SystemExit) as exc:
        _cli(tmp_path, monkeypatch, [base_log()] * n, ["--snapshot-t", "06:01"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "usage:" in err and f"need 2 or 3 logs, got {n}" in err
