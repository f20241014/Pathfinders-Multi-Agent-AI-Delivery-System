# Region Selection for D1

To pick the road network used for the delivery simulation, three candidate areas in Hyderabad/Secunderabad were pulled from OpenStreetMap and compared on graph size and road hierarchy richness.

| Area | Nodes after truncation | % kept | Edges | Primary+secondary+trunk edges |
|---|---|---|---|---|
| Secunderabad | 2,377 | 97% | 6,077 | 617 |
| Begumpet | 1,385 | 97% | 3,398 | 66 |
| Gachibowli | 345 | 96% | 739 | 59 |

## Method

Each candidate was extracted with `ox.graph_from_point`, using a 1500 m box (about 9 km², a square 3 km x 3 km), `network_type="drive"`, `simplify=True`, reduced to the largest strongly connected component, and projected.

## Choice

Secunderabad was selected because it is the only candidate inside the plan's 2,000-5,000 node range, and it has the richest road hierarchy (617 primary/secondary/trunk edges vs. 66 and 59 for the alternatives). Begumpet is below 2,000 nodes with few secondary/primary roads. Gachibowli (345 nodes) is too small for vehicle conflicts.

## Limitations

- OSM snapshot in time — the road network may have changed since extraction.
- Many missing `maxspeed` tags.
- Simplified one-way/turn restrictions.
