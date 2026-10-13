"""Tests for the edge attributes added in src/world/graph_loader.py.

Run from the repo root:  python -m pytest
"""
import networkx as nx
import pytest

from src.world.graph_loader import base_class, load_road_graph, parse_maxspeed


# ---- parse_maxspeed -------------------------------------------------------

def test_parse_maxspeed_plain_number():
    assert parse_maxspeed("60") == 60
    assert parse_maxspeed(50) == 50


def test_parse_maxspeed_mph_converted_to_kmh():
    assert parse_maxspeed("30 mph") == pytest.approx(30 * 1.609344)


def test_parse_maxspeed_list_takes_minimum():
    assert parse_maxspeed(["60", "40"]) == 40
    assert parse_maxspeed("['60', '20']") == 20  # list stored as text in GraphML


def test_parse_maxspeed_unreadable_is_none():
    assert parse_maxspeed(None) is None
    assert parse_maxspeed("signals") is None
    assert parse_maxspeed("0") is None


# ---- base_class -----------------------------------------------------------

def test_base_class_plain():
    assert base_class("residential") == "residential"


def test_base_class_strips_link():
    assert base_class("primary_link") == "primary"


def test_base_class_list_takes_first():
    assert base_class(["living_street", "residential"]) == "living_street"
    assert base_class("['trunk_link', 'primary']") == "trunk"


# ---- the prepared graphs --------------------------------------------------

@pytest.fixture(scope="module", params=["secunderabad_small", "secunderabad"])
def graph(request):
    return load_road_graph(request.param)


def test_every_edge_has_positive_free_flow_time(graph):
    for _, _, data in graph.edges(data=True):
        assert data["free_flow_time"] > 0


def test_at_most_one_edge_per_node_pair(graph):
    for u, v in graph.edges():
        assert len(graph[u][v]) == 1


def test_graph_still_strongly_connected(graph):
    assert nx.is_strongly_connected(graph)
