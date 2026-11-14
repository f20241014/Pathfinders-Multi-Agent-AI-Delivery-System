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