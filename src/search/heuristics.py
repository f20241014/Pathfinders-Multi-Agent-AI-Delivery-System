"""A* heuristic: straight-line distance divided by the fastest speed on the map.

Why it never overestimates (admissible):
- Edge 'length' was computed by OSMnx with the haversine (great-circle) formula,
  and a road can never be shorter than the great-circle line between its ends.
- No edge is faster than max_speed_mps, so no route can beat
  straight-line distance / max speed.
We use haversine on lat/lon (not projected x, y) because UTM distances here can
be up to ~0.19% longer than haversine distances, which could overestimate.
"""
import osmnx as ox


def make_heuristic(G):
    """Return h(node, goal), a lower bound on the travel time in seconds."""
    # Check that every node has lat/lon (load_road_graph adds them).
    for node, data in G.nodes(data=True):
        if "lat" not in data or "lon" not in data:
            raise ValueError(f"node {node} has no lat/lon; load the graph with load_road_graph()")

    # Compute the fastest speed once, not on every call.
    max_speed_kmh = max(data["speed_kmh"] for _, _, data in G.edges(data=True))
    max_speed_mps = max_speed_kmh / 3.6

    def h(node, goal):
        a, b = G.nodes[node], G.nodes[goal]
        # Same great-circle function OSMnx used to measure edge lengths.
        metres = ox.distance.great_circle(a["lat"], a["lon"], b["lat"], b["lon"])
        return metres / max_speed_mps

    return h
