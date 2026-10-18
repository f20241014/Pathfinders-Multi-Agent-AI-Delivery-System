"""Load METR-LA speeds into a pandas DataFrame (rows = time, cols = sensors).

Reads the HDF5 file with h5py because pandas.read_hdf fails on this old file.
"""
import h5py
import numpy as np
import pandas as pd


def load_metr_la(path="data/raw/metr-la.h5"):
    with h5py.File(path, "r") as f:
        g = f["df"]
        values = g["block0_values"][:]
        sensors = g["axis0"][:]
        times = g["axis1"][:]
    if values.shape[0] == len(sensors) and values.shape[1] != len(sensors):
        values = values.T  # make rows = time, cols = sensors
    index = pd.to_datetime(times)
    columns = [s.decode() if isinstance(s, bytes) else str(s) for s in sensors]
    return pd.DataFrame(values, index=index, columns=columns)


if __name__ == "__main__":
    df = load_metr_la()
    print(df.shape)
    print(df.head())
    print("fraction of zeros (missing):", (df == 0).mean().mean())
    print("time range:", df.index.min(), "to", df.index.max())
