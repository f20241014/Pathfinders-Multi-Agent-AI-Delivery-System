"""Edge table for the traffic model: one row per (u, v) road segment.

Reads R2's Secunderabad graph. Parallel edges are merged (the highest road
class wins). Road classes are cleaned (lists and *_link variants). Zones are
500 m grid cells (projected CRS, metres) of the start node, used for spatially correlated noise.
"""
import ast
import networkx as nx

RANK = ["motorway", "trunk", "primary", "secondary", "tertiary",
        "unclassified", "residential", "living_street"]
CELL_M = 500.0   # zone cell size in metres (graph is in a projected CRS)


def rank(c):
    return RANK.index(c) if c in RANK else len(RANK)


def clean_class(raw):
    """'primary_link' -> 'primary'; "['a','b']" -> the highest-ranked of them."""
    if isinstance(raw, str) and raw.startswith("["):
        vals = ast.literal_eval(raw)
    elif isinstance(raw, (list, tuple)):
        vals = list(raw)
    else:
        vals = [raw]
    vals = [str(v).replace("_link", "") for v in vals]
    return min(vals, key=rank)


def load_edge_table(path="data/processed/secunderabad.graphml"):
    G = nx.read_graphml(path)
    if max(abs(float(d["x"])) for _, d in G.nodes(data=True)) < 1000:
        raise ValueError("node x/y look like degrees; expected projected metres")
    best = {}
    for u, v, d in G.edges(data=True):
        c = clean_class(d.get("highway"))
        if (u, v) not in best or rank(c) < rank(best[(u, v)]):
            best[(u, v)] = c
    edges = sorted(best)
    classes = [best[e] for e in edges]
    cells = {}
    zones = []
    for u, _ in edges:
        x, y = float(G.nodes[u]["x"]), float(G.nodes[u]["y"])
        key = (int(x // CELL_M), int(y // CELL_M))
        zones.append(cells.setdefault(key, len(cells)))
    return edges, classes, zones
