"""Build a small (~300 node) test graph from the Secunderabad road network (R2).

Run from the repo root:  python src/world/make_test_graph.py
"""
from pathlib import Path

import networkx as nx
import osmnx as ox

IN_FILE = Path(__file__).resolve().parents[2] / "data" / "processed" / "secunderabad.graphml"
OUT_FILE = Path(__file__).resolve().parents[2] / "data" / "processed" / "secunderabad_small.graphml"
TARGET_NODES = 300


def bfs_ball(G, start, target_size):
    """Grow a connected node set around `start` using BFS on the undirected view."""
    undirected = G.to_undirected()
    ball = set()
    for node in nx.bfs_tree(undirected, start):
        ball.add(node)
        if len(ball) >= target_size:
            break
    return ball


if __name__ == "__main__":
    G = ox.load_graphml(IN_FILE)

    start_node = max(G.nodes, key=lambda n: G.degree(n))
    ball_nodes = bfs_ball(G, start_node, TARGET_NODES)

    G_small = G.subgraph(ball_nodes).copy()
    G_small = ox.truncate.largest_component(G_small, strongly=True)

    strongly_connected = nx.is_strongly_connected(G_small)

    print(f"nodes: {G_small.number_of_nodes()}")
    print(f"edges: {G_small.number_of_edges()}")
    print(f"strongly connected: {strongly_connected}")

    if not strongly_connected:
        raise RuntimeError("secunderabad_small graph is not strongly connected")

    ox.save_graphml(G_small, OUT_FILE)
    print(f"saved to {OUT_FILE}")
