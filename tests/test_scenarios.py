"""Scenario set: R1 loads every file, sizes match D2/D3, times sit inside the simulated period."""

import pytest
import yaml

from src.data.make_scenarios import (
    HORIZON_S,
    SIZES,
    START_S,
    PlaceholderProfile,
    build_config,
    check_servable,
    load_nodes,
)
from src.kr.ontology import NO_TW_END, NO_TW_START, tw_of
from src.sim.run import build_order, build_vehicle


@pytest.fixture(scope="module")
def graph():
    return load_nodes("secunderabad_small")


@pytest.mark.parametrize("size", list(SIZES))
@pytest.mark.parametrize("layout", ["uniform", "clustered", "hotspot"])
def test_config_is_valid_for_r1(graph, size, layout, tmp_path):
    G, nodes = graph
    cfg = build_config(PlaceholderProfile(), G, nodes, size, layout, 0, "test", "x.graphml")
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False))
    cfg = yaml.safe_load(p.read_text())  # round-trips through YAML
    n_veh, n_dep, n_ord = SIZES[size]
    vehicles = [build_vehicle(v) for v in cfg["vehicles"]]  # R1's own loaders
    orders = [build_order(o) for o in cfg["orders"]]
    assert len(vehicles) == n_veh and len(orders) == n_ord
    assert len({v.depot_node for v in vehicles}) == n_dep
    assert sum(o.demand for o in orders) <= sum(v.capacity for v in vehicles)
    node_set = set(G.nodes)
    assert any(tw_of(o) is None for o in orders) and any(tw_of(o) for o in orders)
    for o in orders:
        assert o.node in node_set and o.priority in (1, 2, 3)
        assert all(v is not None for v in vars(o).values())
        assert START_S <= o.release_time <= START_S + HORIZON_S
        tw = tw_of(o)
        if tw is None:
            assert (o.tw_start, o.tw_end) == (NO_TW_START, NO_TW_END)  # R1's "no window"
        else:
            assert o.release_time <= tw[0] < tw[1] <= START_S + HORIZON_S
    assert cfg["scenario_meta"]["demand_source"] == "test"


def test_same_seed_same_file(graph):
    G, nodes = graph
    a = build_config(PlaceholderProfile(), G, nodes, "small", "hotspot", 3, "t", "x")
    b = build_config(PlaceholderProfile(), G, nodes, "small", "hotspot", 3, "t", "x")
    c = build_config(PlaceholderProfile(), G, nodes, "small", "hotspot", 4, "t", "x")
    assert a == b and a["orders"] != c["orders"]


def test_every_order_servable_alone(graph):
    G, nodes = graph
    cfg = build_config(PlaceholderProfile(), G, nodes, "small", "uniform", 0, "t", "x")
    assert check_servable(G, cfg) == []