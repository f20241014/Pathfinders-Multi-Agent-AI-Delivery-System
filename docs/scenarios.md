# R3 · Scenario set (Week 3)

Generator (needs the Amazon profile from `docs/data_profile.md` steps 1-3):
`python -m src.data.make_scenarios --profile-dir data/profile --seeds 0 1 2 3 4 5 6 7 8 9`
Output: `configs/scenarios/<size>_<layout>_s<seed>.yaml`, R1's config format (`python -m src.sim.run --config <file>`).

| Size | Vehicles | Depots | Orders |
|---|---|---|---|
| small | 10 | 2 | 100 |
| medium | 15 | 3 | 200 |
| large | 20 | 3 | 300 |

Layouts: **uniform** (demand spread over 8 k-means zones), **clustered** (Dirichlet(0.5) zone weights: a few busy zones),
**hotspot** (one zone takes about half the demand).

From the Amazon data: packages per stop, package volume, share and width of time windows, window start offset, service time.
Our assumptions: priority split 20/50/30 (express/standard/economy), about 30% of orders released during the run,
homogeneous fleet with capacity = total demand / (vehicles x 0.8), depots at the nodes nearest the k-means centres.
Times are seconds since midnight: simulated period 06:00-10:00 (D4). An order without a window gets R1's defaults
`tw_start = 0.0`, `tw_end = 86400.0` (never `None`, so R1's simulator loads every file).

Each file's `scenario_meta` records the demand source, depots, number of dynamic orders, priority counts and
`orders_unservable_alone` (orders no vehicle could serve even alone at free-flow speed; should be empty).

**Never run experiments on files whose `demand_source` says PLACEHOLDER.** Those come from `--placeholder-profile`,
which exists only to test the pipeline before the Amazon data is downloaded.

## Final configs (Week 4)

Run on your machine (needs `data/profile/` from `docs/data_profile.md` steps 1-3):

```
python -m src.data.make_scenarios --profile-dir data/profile --seeds 0 1 2 3 4 5 6 7 8 9
python -m src.data.make_scenarios --profile-dir data/profile --seeds 0 1 2 3 4 5 6 7 8 9 --large-share 0.3
```

The first line is the main set: 9 scenarios x 10 seeds, small vehicles only (D2). The second adds
a mixed-fleet variant (`*_large30_s<seed>.yaml`): 30% of each fleet are large vehicles, written with
R1's `allowed_road_classes` (no residential, living_street, service or unclassified roads, KR-3).

With large vehicles:
- depots are placed on the part of the map large vehicles can drive (on Secunderabad, 675 of 2,377
  nodes form its largest strongly connected part), so no large vehicle starts stranded;
- the "servable" check uses the road rules: each order must be servable by at least one vehicle
  that may legally reach it (`scenario_meta.orders_unservable_alone` lists any that are not).

Optional KR-6 zones go in a config as `kr_zones: [{id, nodes, start, end, banned_classes}]`
(read by `src.kr.planner_rules.zones_from_config`); the default configs have none. TODO(R2): which
areas are restricted.

Checked on the real map with `--placeholder-profile`: all 9 default and all 9 mixed-fleet configs
for seed 0 build with 0 unservable orders.