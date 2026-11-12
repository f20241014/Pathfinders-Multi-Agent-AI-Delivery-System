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
