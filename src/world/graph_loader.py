"""Download and compare candidate Hyderabad road networks (R2).

Run from the repo root:  python src/world/graph_loader.py
"""
import ast
import statistics
from collections import Counter
from pathlib import Path

import osmnx as ox
from pyproj import Transformer

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


# ---------------------------------------------------------------------------
# Edge attributes for search (road class, speed, free-flow travel time)
# ---------------------------------------------------------------------------

# Fallback speeds (km/h) used when a road class has fewer than 5 tagged edges.
DEFAULT_SPEEDS_KMH = {
    "motorway": 80,
    "trunk": 60,
    "primary": 50,
    "secondary": 40,
    "tertiary": 35,
    "unclassified": 30,
    "residential": 25,
    "living_street": 15,
}
OTHER_SPEED_KMH = 25         # any class not in the dict above
MIN_TAGGED_FOR_MEDIAN = 5    # need at least this many tagged edges to trust a median
MPH_TO_KMH = 1.609344


def _as_list(value):
    """Turn a list, or a string that looks like a list ("['a', 'b']"), into a list.

    GraphML stores everything as text, so OSM lists can come back as strings.
    Anything else is returned as a one-item list.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.startswith("["):
        return ast.literal_eval(value)  # safely parse the text "['a', 'b']" into a list
    return [value]


def base_class(highway):
    """Simplify an OSM highway tag to one road class, e.g. 'primary_link' -> 'primary'."""
    first = _as_list(highway)[0]          # if OSM gave several classes, use the first
    return str(first).removesuffix("_link")  # a slip road counts as its main road


def parse_maxspeed(value):
    """Convert an OSM maxspeed tag to km/h, or None if it is missing or unreadable.

    Examples: "60" -> 60.0, "30 mph" -> 48.28, ["60", "40"] -> 40.0, "signals" -> None.
    """
    if value is None:
        return None
    items = _as_list(value)
    if len(items) > 1:
        # Several limits on one edge: be cautious and take the slowest readable one.
        speeds = [parse_maxspeed(item) for item in items]
        speeds = [s for s in speeds if s is not None]
        return min(speeds) if speeds else None

    item = items[0]
    if isinstance(item, (int, float)):
        speed = float(item)
    else:
        text = str(item).strip().lower()
        try:
            if text.endswith("mph"):
                speed = float(text.removesuffix("mph")) * MPH_TO_KMH
            else:
                speed = float(text)
        except ValueError:
            return None                   # e.g. "signals" or "none"
    if speed != speed or speed <= 0:      # NaN (speed != speed) or impossible value
        return None
    return speed


def add_lat_lon(G):
    """Add 'lat' and 'lon' (degrees) to every node by un-projecting its x, y.

    Our saved graphs are projected (x, y in metres) and lost the original
    degrees. This only changes the graph in memory, never the file.
    """
    to_degrees = Transformer.from_crs(G.graph["crs"], "EPSG:4326", always_xy=True)
    for _, data in G.nodes(data=True):
        data["lon"], data["lat"] = to_degrees.transform(data["x"], data["y"])
    return G


def add_edge_attributes(G):
    """Add road_class, speed_kmh, speed_imputed and free_flow_time to every edge."""
    # Pass 1: read the class and any tagged speed, and collect tagged speeds per class.
    tagged = {}  # road class -> list of tagged speeds
    for _, _, data in G.edges(data=True):
        data["road_class"] = base_class(data["highway"])
        data["speed_kmh"] = parse_maxspeed(data.get("maxspeed"))
        if data["speed_kmh"] is not None:
            tagged.setdefault(data["road_class"], []).append(data["speed_kmh"])

    # Choose one fill-in speed per class: median of this graph's tagged edges if
    # there are enough of them, otherwise the default table.
    fill_speed = {}
    for road_class, speeds in tagged.items():
        if len(speeds) >= MIN_TAGGED_FOR_MEDIAN:
            fill_speed[road_class] = statistics.median(speeds)

    # Pass 2: fill gaps and compute travel time.
    for _, _, data in G.edges(data=True):
        data["speed_imputed"] = data["speed_kmh"] is None
        if data["speed_imputed"]:
            road_class = data["road_class"]
            default = DEFAULT_SPEEDS_KMH.get(road_class, OTHER_SPEED_KMH)
            data["speed_kmh"] = fill_speed.get(road_class, default)
        speed_mps = data["speed_kmh"] / 3.6               # km/h -> metres per second
        data["free_flow_time"] = data["length"] / speed_mps  # seconds
    return G


def keep_fastest_parallel_edges(G):
    """For each (u, v) keep only the edge with the smallest free_flow_time."""
    to_remove = []
    for u, v in set(G.edges()):                  # each distinct (u, v) pair once
        edges = G[u][v]                          # {key: data} for all parallel edges
        if len(edges) > 1:
            best_key = min(edges, key=lambda k: edges[k]["free_flow_time"])
            to_remove += [(u, v, k) for k in edges if k != best_key]
    G.remove_edges_from(to_remove)
    return G


def load_road_graph(name="secunderabad", verbose=False):
    """Load a saved graph and prepare it for search (lat/lon, speeds, no parallel edges)."""
    G = ox.load_graphml(OUT_DIR / f"{name}.graphml")
    add_lat_lon(G)
    add_edge_attributes(G)
    edges_before = G.number_of_edges()
    keep_fastest_parallel_edges(G)
    if verbose:
        print_speed_report(G, edges_before)
    return G


def print_speed_report(G, edges_before):
    """Print edge counts and how many speeds had to be imputed."""
    print(f"edges: {edges_before} before, {G.number_of_edges()} after parallel-edge removal")
    total = Counter()
    imputed = Counter()
    for _, _, data in G.edges(data=True):
        total[data["road_class"]] += 1
        imputed[data["road_class"]] += data["speed_imputed"]
    n_total, n_imputed = sum(total.values()), sum(imputed.values())
    print(f"imputed speeds: {n_imputed}/{n_total} ({n_imputed / n_total:.1%})")
    for road_class, count in total.most_common():
        speeds = sorted({d["speed_kmh"] for _, _, d in G.edges(data=True)
                         if d["road_class"] == road_class and d["speed_imputed"]})
        print(f"  {road_class:14s} {imputed[road_class]:5d}/{count:<5d} "
              f"({imputed[road_class] / count:6.1%})  filled with {speeds} km/h")
    print(f"max speed_kmh: {max(d['speed_kmh'] for _, _, d in G.edges(data=True))}")


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