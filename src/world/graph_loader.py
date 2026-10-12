"""Download and compare candidate Hyderabad road networks (R2).

Run from the repo root:  python src/world/graph_loader.py
"""
from collections import Counter
from pathlib import Path

import osmnx as ox

# Approximate centres (lat, lon). Check each one on Google Maps and nudge if needed.
AREAS = {
    "secunderabad": (17.4399, 78.4983),
    "begumpet": (17.4440, 78.4640),
    "gachibowli": (17.4401, 78.3489),
}
RADIUS_M = 1500  # metres from the centre, roughly 9 km2

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


def road_class_counts(G):
    """Count edges per highway class (OSM sometimes stores a list)."""
    counts = Counter()
    for _, _, data in G.edges(data=True):
        hw = data["highway"]
        counts[hw[0] if isinstance(hw, list) else hw] += 1
    return counts


def load_area(name, centre, radius_m=RADIUS_M):
    """Download one area, keep the largest strongly connected component, project it."""
    G = ox.graph_from_point(centre, dist=radius_m, network_type="drive", simplify=True)
    nodes_before = G.number_of_nodes()
    G = ox.truncate.largest_component(G, strongly=True)
    nodes_after = G.number_of_nodes()
    G = ox.project_graph(G)

    print(f"\n{name}: nodes {nodes_before} -> {nodes_after} "
          f"({nodes_after / nodes_before:.0%} kept), edges {G.number_of_edges()}")
    print(dict(road_class_counts(G).most_common()))
    return G


import time

if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, centre in AREAS.items():
        out_file = OUT_DIR / f"{name}.graphml"
        if out_file.exists():
            print(f"{name}: already downloaded, skipping")
            continue
        for attempt in range(1, 4):
            try:
                G = load_area(name, centre)
                ox.save_graphml(G, out_file)
                break
            except Exception as e:
                print(f"{name}: attempt {attempt} failed ({type(e).__name__})")
                time.sleep(10 * attempt)
        else:
            print(f"{name}: gave up after 3 attempts")
    print(f"\nSaved GraphML files to {OUT_DIR}")