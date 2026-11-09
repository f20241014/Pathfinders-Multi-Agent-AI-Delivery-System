"""Shared, frozen-at-now prediction + observed incident feed for BOTH planners."""
import math
import networkx as nx


class WorldTravel:
    """Cache shortest paths per snapshot/road-class profile, not future truth.

    A snapshot rebuild is required on each incident or forecast refresh. Paths
    use the same fastest parallel-edge convention as the existing World.
    """

    def __init__(self, world, now):
        self.world, self.now = world, now
        self.graphs, self.paths = {}, {}

    def graph_for(self, vehicle):
        profile = tuple(sorted(vehicle.allowed_road_classes or []))
        if profile not in self.graphs:
            g = nx.DiGraph()
            g.add_nodes_from(self.world.G.nodes)
            for u, v in self.world.G.edges():
                key = self.world.edge_key(u, v)
                data = self.world.G[u][v][key]
                classes = data.get('highway', '')
                classes = classes if isinstance(classes, list) else [classes]
                if profile and not any(c in profile for c in classes):
                    continue
                if self.world.is_blocked(u, v, self.now, key):
                    continue
                seconds = self.world.predicted_time(u, v, self.now)
                seconds *= self.world.spike_multiplier(u, v, self.now, key)
                if not math.isfinite(seconds) or seconds < 0:
                    raise ValueError('invalid predicted travel time')
                g.add_edge(u, v, weight=seconds)
            self.graphs[profile] = g
        return profile, self.graphs[profile]

    def path(self, vehicle, source, target):
        profile, graph = self.graph_for(vehicle)
        key = (profile, source)
        if key not in self.paths:
            try:
                self.paths[key] = nx.single_source_dijkstra(graph, source)
            except nx.NodeNotFound:
                self.paths[key] = ({}, {})
        distances, paths = self.paths[key]
        return distances.get(target, math.inf), paths.get(target, [])

    def __call__(self, vehicle, source, target):
        return self.path(vehicle, source, target)[0]
