# Data profile — Amazon Last Mile Routing Research Challenge 2021

Owner: R3 · Fill the numbers from `data/profile/summary.json` after running `src/data/profile_amazon.py`.

## Source
- Merchán et al. (2022), Amazon Last Mile Routing Research Challenge dataset, AWS Open Data.
- S3 bucket: `s3://amazon-last-mile-challenges/almrrc2021/` (public, `--no-sign-request`).
- License: **CC BY-NC 4.0** — non-commercial use, credit Amazon.
- Files used: `route_data.json`, `package_data.json` (training split, `model_build_inputs/`).
- Files **not** used: `travel_times.json` (largest file; we use our own OSM travel times), `actual_sequences.json`, `invalid_sequence_scores.json`.
- Download size of what we used: ___ MB · Routes profiled: ___ (all / subset of ___)

## Fields used

| Field | Level | Used for |
|---|---|---|
| stops (type ≠ Station) | route | stops per route → orders per vehicle |
| packages per stop | stop | demand per order |
| dimensions (depth × height × width) | package | demand size → capacity units |
| time_window start/end | package | share of orders with a window, window width, window position |
| planned_service_time_seconds | package | service_time |
| executor_capacity_cm3 | route | vehicle capacity, utilization |
| departure_time_utc | route | to place windows relative to shift start |

Fields **ignored on purpose**: lat/lng (obfuscated, no geography transfers), zone_id (Amazon's own zones, not ours), route_score (quality label, not demand).

## Results

| Statistic | p5 | p25 | median | p75 | p95 | mean |
|---|---|---|---|---|---|---|
| Stops per route | | | | | | |
| Packages per stop | | | | | | |
| Package volume (cm³) | | | | | | |
| Time-window width (h) | | | | | | |
| Service time per stop (s) | | | | | | |
| Capacity utilization | | | | | | |

- Share of packages with a time window: ___ %
- Share of stops with at least one windowed package: ___ %
- Is service time per package or repeated per stop? ___ (check: compare `service_sum_s` vs `service_max_s`)

Plots: `stops_per_route.png`, `packages_per_stop.png`, `package_volume.png`, `tw_width.png`, `service_time.png`.

## How this becomes orders (input to D3)
- Orders per scenario: 100–300 (D3); per vehicle ≈ sampled from stops-per-route, scaled to a 4-hour window (D4).
- Demand = sampled packages per stop × sampled volumes → converted to abstract units.
- Time windows: present with the measured probability; width and start offset sampled from the empirical quantiles.
- Locations: graph nodes sampled from demand zones on **our** Hyderabad map (Week 2), not from Amazon coordinates.

## Limitations to state in the report
- US data from 2018, five metro areas; Hyderabad demand may differ.
- Coordinates are obfuscated, so only statistics transfer, not spatial patterns.
- Priority tiers (1–3) do not exist in the data; we assign them synthetically (state the split).

## Fallback (if download fails)
Fit distributions to Solomon VRPTW instances and say so in the proposal/report.