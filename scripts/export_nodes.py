"""
R3 · Write the map's nodes to data/map/nodes.csv (columns node, x, y) for the order generator.

    python scripts/export_nodes.py

Reads data/processed/secunderabad.graphml through R2's load_road_graph, the same loader R1's World
uses, so every node id in the CSV exists in the simulator's graph. x, y are the projected
coordinates stored in the graphml (only used to group nodes into demand zones).

Options: --graph secunderabad_small (any name in data/processed/), --out <path>.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def export_nodes(graph_name: str, out: Path) -> int:
    """Write node, x, y for every node of the graph; returns the number of rows."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))  # so "python scripts/export_nodes.py" finds src/
    import pandas as pd

    from src.world.graph_loader import load_road_graph

    G = load_road_graph(graph_name)
    rows = [(int(n), float(d["x"]), float(d["y"])) for n, d in G.nodes(data=True)]
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["node", "x", "y"]).to_csv(out, index=False)
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    ap.add_argument("--graph", default="secunderabad", help="name of data/processed/<name>.graphml")
    ap.add_argument("--out", default="data/map/nodes.csv")
    a = ap.parse_args()
    n = export_nodes(a.graph, Path(a.out))
    print(f"wrote {n} nodes to {a.out}")


if __name__ == "__main__":
    main()
