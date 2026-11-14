# Model card: traffic forecaster (R6)

## Purpose
Forecast per-edge congestion multipliers (travel time = free-flow time x multiplier)
for the planners in the delivery simulator. Intended use: this project's simulation
only. Not validated for real Hyderabad traffic.

## Data
- METR-LA (Li et al. 2018): 207 sensors, 5-minute speeds, 1 Mar to 27 Jun 2012,
  34,272 rows. Zeros are missing readings (8.1% overall) and are masked, never
  treated as real speeds.
- Target: speed ratio = speed / free-flow speed (free-flow = 95th percentile of the
  sensor's speeds, computed on TRAIN only), clipped to [0.05, 1.0].
- Road graph: R2's Secunderabad OSM graph (6,056 merged edges).

## Splits (chronological, no shuffling)
| split | rows | period | missing |
|---|---|---|---|
| train | 23,990 | 2012-03-01 to 2012-05-23 | 7.1% |
| val | 3,427 | 2012-05-23 to 2012-06-04 | 7.0% |
| test | 6,855 | 2012-06-04 to 2012-06-27 | 12.1% |
Normalisation statistics and free-flow speeds use train rows only. Simulation days
come from the test period only.

## Model
- Shared 2-layer LSTM, hidden size 64, dropout 0.1, 51,395 parameters, 209 KB.
- Input: last 12 steps (1 hour) of ratio, plus sin/cos time of day and weekday.
- Output: ratio at +15, +30, +60 min, predicted as current ratio + learned change.
- Loss: masked MAE. Adam, lr 1e-3, batch 512, early stopping on validation MAE.
  Seed 42. Hyperparameters: reports/lstm_v1_config.json.
- Frozen weights: sha256 ba74d9d5...a7764 (full hashes in reports/model_freeze.json).

## Results (test split, MAE in speed-ratio units, same cells for all methods)
| horizon | persistence | historical average | LSTM |
|---|---|---|---|
| 15 min | 0.0518 | 0.0624 | 0.0446 |
| 30 min | 0.0624 | 0.0624 | 0.0534 |
| 60 min | 0.0800 | 0.0624 | 0.0655 |
The LSTM beats both baselines at 15 and 30 min. At 60 min the historical average
is better, so the predictor uses it there. LSTM error peaks at 15:00-18:00 LA time
(about 0.06-0.065 at 15 min), when traffic changes fastest.

## In-simulation checks
- Full-network refresh: about 0.17 s mean, 0.20 s max for 6,056 edges (cached
  per 5-minute step, 8 steps kept).
- Mean absolute multiplier error vs simulator truth: 0.131 / 0.173 / 0.249 at
  15 / 30 / 60 min (single morning, so indicative only).
- No-future-leak test: doubling all congestion after "now" leaves predictions unchanged.

## Ablation (pilot, seeds 9001-9005, independent mode)
- 06:00 start: no measurable effect (0.17 s).
- 08:00 start (rush hour): planning with the forecast was about 38 s faster than
  without it (rate 10: 37.6 s, CI [20.7, 58.1]; rate 60: 39.1 s, CI [22.3, 59.6]),
  roughly 3-4% of mean delivery time. The effect did not grow with disruption rate.
- The 08:00 start was chosen after seeing the 06:00 null; the final report should
  rerun on fresh seeds with a pre-fixed start time.

## Limitations
- Trained on Los Angeles highway sensors; applied to Hyderabad roads by assumption
  (road class mapped to sensor group, LA peaks shifted +1 hour). Hyderabad accuracy
  was never measured.
- The simulator's traffic is built from the same sensor patterns the model learns,
  so the ablation shows the forecast helps with recurring, predictable congestion,
  not that it works on real roads.
- It forecasts recurring congestion only, not closures or incidents.
- Test period has more missing data (12.1%); gaps were forward-filled for inputs.
- Currently all seeds read the same simulated morning (day 1 of the table).
- The 60-minute forecast is a sensor-group average, so it smooths single-edge jams.
