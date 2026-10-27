
import networkx as nx


def build_test_graph():
    """Create a small directed road network with an alternate route."""
    graph = nx.DiGraph()

    graph.add_weighted_edges_from([
        ("A", "B", 1),
        ("B", "D", 2),
        ("A", "C", 2),
        ("C", "D", 2),
    ])

    return graph


def test_astar_finds_shortest_path():
    """Check the reference shortest path and its cost."""
    graph = build_test_graph()

    path = nx.astar_path(
        graph,
        source="A",
        target="D",
        weight="weight",
    )
    cost = nx.path_weight(graph, path, weight="weight")

    assert path[0] == "A"
    assert path[-1] == "D"
    assert cost == 3


def test_astar_reroutes_after_road_closure():
    """Check that A* uses the alternate route after a closure."""
    graph = build_test_graph()

    graph.remove_edge("B", "D")

    path = nx.astar_path(
        graph,
        source="A",
        target="D",
        weight="weight",
    )
    cost = nx.path_weight(graph, path, weight="weight")

    assert path == ["A", "C", "D"]
    assert cost == 4


def test_astar_handles_unreachable_goal():
    """Check the expected behavior when no route exists."""
    graph = build_test_graph()
    graph.remove_edge("B", "D")
    graph.remove_edge("C", "D")

    try:
        nx.astar_path(graph, source="A", target="D", weight="weight")
    except nx.NetworkXNoPath:
        pass
    else:
        raise AssertionError("Expected NetworkXNoPath for unreachable goal")
