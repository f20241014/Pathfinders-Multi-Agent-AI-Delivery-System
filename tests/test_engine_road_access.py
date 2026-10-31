from src.kr.engine import check_road_access


def test_all_roads_allowed():
    passed, trace = check_road_access(
        None, ["residential", "primary", "secondary"]
    )
    assert passed is True


def test_restricted_road():
    passed, trace = check_road_access(
        None, ["residential", "motorway"]
    )
    assert passed is False