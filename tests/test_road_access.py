
from src.kr.rules import road_allowed


def test_residential_road_allowed():
    assert road_allowed(None, "residential") is True


def test_primary_road_allowed():
    assert road_allowed(None, "primary") is True


def test_motorway_restricted():
    assert road_allowed(None, "motorway") is False


def test_unknown_road_rejected():
    assert road_allowed(None, "unknown_road") is False


def test_link_road_class():
    assert road_allowed(None, "primary_link") is True
