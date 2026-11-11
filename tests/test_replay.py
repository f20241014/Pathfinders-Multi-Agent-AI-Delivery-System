"""Tests for the Week 4 replay (src/viz/replay.py). No network, no large files."""
import json
from pathlib import Path

import matplotlib
import networkx as nx
import pytest
import yaml

matplotlib.use("Agg")

from src.viz import replay  # noqa: E402
from src.viz.replay import LogFormatError, load_log, state_at  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
START = 21600.0


def small_graph():
    """5 nodes on a small square-ish layout around Secunderabad, with lat/lon."""
    G = nx.MultiDiGraph()
    coords = {1: (17.430, 78.490), 2: (17.430, 78.500), 3: (17.440, 78.500),
              4: (17.440, 78.490), 5: (17.435, 78.495)}
    for n, (lat, lon) in coords.items():
        G.add_node(n, lat=lat, lon=lon, x=lon, y=lat)
    for u, v, hw in [(1, 2, "primary"), (2, 3, "residential"), (3, 4, "residential"),
                     (4, 1, "secondary"), (1, 5, "residential"), (5, 3, "tertiary")]:
        G.add_edge(u, v, 0, highway=hw, length=1000.0)
        G.add_edge(v, u, 0, highway=hw, length=1000.0)
    return G


def ev(t, event, payload, agent="env"):
    return {"run_id": "test_run", "mode": "independent", "seed": 1, "scenario": "unit",
            "rate": 5.0, "t": float(t), "agent_id": agent, "event": event,
            "payload": payload}


CONFIG = {
    "vehicles": [{"id": "V1", "depot_node": 1, "current_node": 1, "capacity": 100},
                 {"id": "V2", "depot_node": 4, "capacity": 100}],
    "orders": [
        {"id": "O1", "node": 2, "demand": 5, "release_time": 0.0},
        {"id": "O2", "node": 3, "demand": 5, "release_time": START + 500},
        {"id": "O3", "node": 5, "demand": 5, "release_time": 0.0},
    ],
}


def events():
    return [
        ev(START, "sim_start", {"start_time_s": START, "duration_seconds": 1200.0,
                                "n_vehicles": 2, "n_orders": 3}),
        ev(START, "edge_enter", {"edge": [1, 2, 0], "expected_duration": 100.0}, "V1"),
        ev(START + 100, "edge_exit", {"node": 2}, "V1"),
        ev(START + 150, "disruption", {"type": "closure", "edge": [4, 1, 0],
                                       "magnitude": None, "duration": 300.0,
                                       "expiry": START + 450}),
        ev(START + 160, "disruption", {"type": "traffic_spike", "edge": [2, 3, 0],
                                       "magnitude": 2.0, "duration": 200.0,
                                       "expiry": START + 360}),
        ev(START + 200, "blocked_wait", {"edge": [4, 1, 0]}, "V2"),
        ev(START + 400, "order_delivered", {"order_id": "O1", "node": 2, "demand": 5}, "V1"),
        ev(START + 420, "new_order", {"order_id": "dyn_1", "release_time": START + 420}),
        ev(START + 430, "closure_skipped", {"attempts": 20}),
        ev(START + 600, "edge_enter", {"edge": [4, 1, 0], "expected_duration": 50.0}, "V2"),
        ev(START + 700, "order_failed", {"order_id": "O2", "node": 3,
                                         "reason": "not_on_route"}, "V1"),
        ev(START + 1200, "sim_complete", {"delivered": 1, "failed": 1}),
    ]


# --------------------------------------------------------------------------- load_log

def write_lines(path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_load_log_reads_valid_file(tmp_path):
    path = write_lines(tmp_path / "ok.jsonl", [json.dumps(e) for e in events()])
    assert len(load_log(path)) == len(events())


def test_load_log_rejects_bad_json_with_line_number(tmp_path):
    lines = [json.dumps(e) for e in events()[:2]] + ["{not json"]
    path = write_lines(tmp_path / "bad.jsonl", lines)
    with pytest.raises(LogFormatError, match="line 3"):
        load_log(path)


def test_load_log_rejects_missing_key(tmp_path):
    broken = events()[1]
    del broken["payload"]
    path = write_lines(tmp_path / "missing.jsonl", [json.dumps(events()[0]), json.dumps(broken)])
    with pytest.raises(LogFormatError, match=r"line 2.*payload"):
        load_log(path)


# --------------------------------------------------------------------------- vehicles

def test_driving_vehicle_is_at_midpoint():
    G = small_graph()
    s = state_at(events(), START + 50, CONFIG, G)
    v1 = s.vehicles["V1"]
    assert v1.state == "driving"
    assert v1.fraction == pytest.approx(0.5)
    assert v1.lat == pytest.approx(17.430)
    assert v1.lon == pytest.approx(78.495)


def test_vehicle_sits_at_node_after_edge_exit():
    G = small_graph()
    s = state_at(events(), START + 120, CONFIG, G)
    v1 = s.vehicles["V1"]
    assert v1.state == "stationary" and v1.node == 2
    assert (v1.lat, v1.lon) == pytest.approx((17.430, 78.500))


def test_vehicle_before_first_event_uses_config_start():
    s = state_at(events(), START - 10, CONFIG, small_graph())
    assert s.vehicles["V2"].node == 4 and s.vehicles["V2"].state == "stationary"
    no_cfg = state_at(events(), START + 10, None, small_graph())
    assert "V2" not in no_cfg.vehicles          # no config and no event yet: not shown


def test_waiting_state_after_blocked_wait():
    G = small_graph()
    assert state_at(events(), START + 230, CONFIG, G).vehicles["V2"].state == "waiting"
    assert state_at(events(), START + 260, CONFIG, G).vehicles["V2"].state == "waiting"
    # More than 60 s after the last blocked_wait: stationary again.
    assert state_at(events(), START + 261, CONFIG, G).vehicles["V2"].state == "stationary"
    # An edge_enter ends the wait.
    assert state_at(events(), START + 610, CONFIG, G).vehicles["V2"].state == "driving"


# --------------------------------------------------------------------------- disruptions

def test_closure_active_exactly_in_t_to_expiry():
    evs = events()
    assert state_at(evs, START + 149.99, CONFIG).closures == []
    assert state_at(evs, START + 150, CONFIG).closures == [(4, 1, 0)]
    assert state_at(evs, START + 449.99, CONFIG).closures == [(4, 1, 0)]
    assert state_at(evs, START + 450, CONFIG).closures == []


def test_spike_has_edge_and_magnitude():
    s = state_at(events(), START + 200, CONFIG)
    assert s.spikes == [((2, 3, 0), 2.0)]
    assert state_at(events(), START + 360, CONFIG).spikes == []


# --------------------------------------------------------------------------- orders

def test_order_state_transitions():
    evs = events()
    states = {t: state_at(evs, START + t, CONFIG).orders for t in (0, 450, 550, 800)}
    assert states[0]["O2"].state == "not_released"
    assert states[0]["O1"].state == "open"
    assert states[450]["O1"].state == "delivered"
    assert states[450]["O2"].state == "not_released"
    assert states[550]["O2"].state == "open"
    assert states[800]["O2"].state == "failed"
    assert states[800]["O3"].state == "open"


def test_counters():
    c = state_at(events(), START + 800, CONFIG).counters
    assert c["delivered"] == 1 and c["failed"] == 1
    assert c["total_orders"] == 4            # O1, O2, O3 + dyn_1
    assert c["closures_active"] == 0 and c["closures_total"] == 1
    assert c["spikes_active"] == 0 and c["spikes_total"] == 1
    assert c["closure_skipped"] == 1
    early = state_at(events(), START + 200, CONFIG).counters
    assert early["closures_active"] == 1 and early["spikes_active"] == 1
    assert early["closure_skipped"] == 0


def test_new_order_without_node_is_counted_not_drawn():
    G = small_graph()
    s = state_at(events(), START + 450, CONFIG, G)
    dyn = s.orders["dyn_1"]
    assert dyn.dynamic and dyn.node is None and dyn.lat is None
    assert s.counters["new_orders"] == 1 and s.counters["undrawn_orders"] == 1

    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    renderer = replay.ReplayRenderer(ax, G)
    renderer.update(s)
    drawn_open = renderer.open_orders.get_offsets()
    plt.close(fig)
    assert len(drawn_open) == 1                # only O3 (O2 not released, dyn_1 has no node)


def test_new_order_with_node_is_drawn():
    evs = events() + [ev(START + 430, "new_order", {"order_id": "dyn_2", "node": 5,
                                                    "release_time": START + 430})]
    s = state_at(evs, START + 500, CONFIG, small_graph())
    assert s.orders["dyn_2"].node == 5 and s.orders["dyn_2"].lat == pytest.approx(17.435)


def test_clock_and_time_parsing():
    assert replay.format_clock(21600) == "06:00"
    assert replay.format_clock(25260.5) == "07:01"
    assert replay.parse_time("07:30") == 27000
    assert replay.parse_time("27000") == 27000


# --------------------------------------------------------------------------- rendering

def test_render_three_frames_to_gif(tmp_path):
    out = tmp_path / "replay.gif"
    info = replay.render_animation(events(), small_graph(), out, CONFIG, step=100,
                                   fps=5, start=START, end=START + 200, dpi=40)
    assert info["frames"] == 3
    assert out.exists() and out.stat().st_size > 0


def test_integration_real_map_snapshot(tmp_path):
    map_file = REPO / "data" / "processed" / "secunderabad.graphml"
    if not map_file.exists():
        pytest.skip("road graph file missing")
    from src.sim.run import run_from_config

    config = yaml.safe_load((REPO / "configs" / "sim_default.yaml").read_text(encoding="utf-8"))
    config["log_path"] = str(tmp_path / "sim.jsonl")      # never write into logs/
    log_path = run_from_config(config)
    evs = load_log(log_path)
    assert evs[0]["event"] == "sim_start" and evs[-1]["event"] == "sim_complete"

    graph = replay.load_graph_for(config)
    start, end = replay.time_range(evs)
    png = tmp_path / "snap.png"
    state = replay.render_snapshot(evs, graph, start + 600, png, config, dpi=50)
    assert png.exists() and png.stat().st_size > 0
    assert state.vehicles["V1"].lat is not None
    assert state.counters["total_orders"] >= 2
