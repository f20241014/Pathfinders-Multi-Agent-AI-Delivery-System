## Transfer limitation (R6, for the report)

The forecaster was trained and tested on METR-LA, Los Angeles highway sensors
from March to June 2012. Our simulator applies those patterns to Hyderabad
roads by assumption: each OSM road class is mapped to a group of sensors with a
similar rush-hour dip, LA peaks are shifted by one hour, and neighbouring roads
share spatially correlated noise. We never measured traffic in Hyderabad, so
the reported errors (MAE 0.0446 / 0.0534 / 0.0655 in speed-ratio units at 15 /
30 / 60 minutes) describe METR-LA, not Hyderabad. Because the simulator's
ground-truth traffic is built from the same family of sensor patterns the model
learned, the ablation (about 38 s faster delivery with the forecast, pilot)
shows that forecasts help when congestion is recurring and predictable; it does
not show the same gain on real Hyderabad roads. The forecast is also largely
reactive: on the example road it lags the actual multiplier by about one step
and under-predicts the peak. It forecasts only recurring congestion, not
closures or incidents. The limitation could be reduced by logging a few real
Hyderabad travel times at different hours to calibrate peak timing and
magnitude, or by training on local data.
