# Prediction module (R6)

Traffic forecasting: METR-LA data prep, baselines, LSTM, predictor interface.

## Setup and run

1. Python 3.10+ (developed on 3.12). `pip install -r requirements.txt`
2. Get `metr-la.h5` from the Data Preparation section of the DCRNN repository
   (https://github.com/liyaguang/DCRNN). Save it at `data/raw/metr-la.h5`.
   This folder is git-ignored; do not commit the data.
3. The loader uses h5py because `pandas.read_hdf` fails on this file.
4. From the repo root, in this order:
   - `python -m src.prediction.data_prep`
   - `python -m src.prediction.baselines`
   - `python -m src.prediction.train`
   - `python -m src.prediction.figures`
   - `pytest`

Results: `reports/model_mae.csv`. The predictor uses the LSTM for 15 and 30 minutes
and the historical average for 60 minutes (it was better there).
