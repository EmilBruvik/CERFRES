#!/usr/bin/env python3
"""
Script to fix Germany PV distribution in existing per-farm NetCDF files.
Reads the existing grid, extracts the Germany distributed PV (assumed to be based on 
farm capacity due to missing population weights), and redistributes it using 
the correct population raster.

Does NOT read external weather data.
Uses known old weights (farm capacity) to recover the time series, then applies new weights (population).
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
import rasterio
import argparse
import datetime
from scipy.spatial import cKDTree

# Setup path to find functions.py
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Helper to read CSV (Copied to be standalone)
def _read_tracker_csv(path: str) -> pd.DataFrame:
    for enc in ("utf-8", "latin1", "cp1252"):
        try:
            return pd.read_csv(path, sep=";", decimal=",", encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(
        path,
        sep=";",
        decimal=",",
        encoding="latin1",
        encoding_errors="replace",
        low_memory=False,
    )

# GridIndexer class (Copied from weather_energy_monthly.py)
class GridIndexer:
    def __init__(self, lat2d: np.ndarray, lon2d: np.ndarray):
        self.shape = lat2d.shape
        self.n_points = lat2d.size
        lon_norm = lon2d.ravel() % 360.0
        lat_flat = lat2d.ravel()
        p_main = np.column_stack((lat_flat, lon_norm))
        p_left = np.column_stack((lat_flat, lon_norm - 360.0))
        p_right = np.column_stack((lat_flat, lon_norm + 360.0))
        self.tree = cKDTree(np.vstack((p_main, p_left, p_right)))

    def map_points(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        lon_q = lon % 360.0
        pts = np.column_stack((lat, lon_q))
        _, idx = self.tree.query(pts, k=1)
        idx_orig = idx % self.n_points
        y, x = np.unravel_index(idx_orig, self.shape)
        return y.astype(int), x.astype(int)

def main():
    parser = argparse.ArgumentParser(description="Fix Germany PV distributed component in existing NetCDF grid outputs.")
    parser.add_argument("--year", default="2024", help="Year (default: 2024)")
    parser.add_argument("--month", default="03", help="Month (default: 03)")
    args = parser.parse_args()

    year = args.year
    month = args.month.zfill(2)

    # Paths (Hardcoded based on user context)
    grid_file = Path(f"/Data/gfi/vindenergi/nab015/highres-renewable-dataset/per-farm-production/{year}/{month}_{year}_pv_wind_grid.nc")
    tracker_csv = "/Data/gfi/vindenergi/nab015/Solar_data/Global-Solar-Power-Tracker-February-2026.csv"
    pop_tif = Path("/Data/gfi/vindenergi/nab015/Solar_data/population_distribution/deu_pop_2026_CN_1km_R2025A_UA_v1.tif")

    if not grid_file.exists():
        print(f"Error: Grid file not found: {grid_file}")
        sys.exit(1)

    print(f"Processing {grid_file}...")
    
    # 1. Open dataset
    # We load variables lazily, then access .values to load specific parts into memory
    ds = xr.open_dataset(grid_file, engine="h5netcdf")
    
    # Initialize indexer
    print("Mapping grid coordinates...")
    lat2d = ds["latitude"].values
    lon2d = ds["longitude"].values
    indexer = GridIndexer(lat2d, lon2d)

    # 2. Calculate OLD weights (Farm Capacity) for Germany
    print("Mapping old farm locations (fallback weights)...")
    df_tracker = _read_tracker_csv(tracker_csv)
    df_de = df_tracker[df_tracker["Country/Area"] == "Germany"].copy()
    
    # Filter for Operating
    # Attempt to use functions logic if available, else standard fallback
    op_status = {"Operating"}
    if "functions" in sys.modules:
        try:
            import functions
            if hasattr(functions, "operating_farms"):
                op_status = set(functions.operating_farms("Germany", "solar"))
        except ImportError:
            pass
    
    df_de = df_de[df_de["Status"].isin(op_status)].copy()
    
    df_de["Latitude"] = pd.to_numeric(df_de["Latitude"], errors="coerce")
    df_de["Longitude"] = pd.to_numeric(df_de["Longitude"], errors="coerce")
    df_de = df_de.dropna(subset=["Latitude", "Longitude"])
    
    y_old, x_old = indexer.map_points(df_de["Latitude"].values, df_de["Longitude"].values)
    caps = pd.to_numeric(df_de["Capacity (MW)"], errors="coerce").fillna(0.0).values
    
    # Group by grid cell to sum capacity
    df_old = pd.DataFrame({"y": y_old, "x": x_old, "cap": caps})
    # Filter out zero caps to avoid division/bad weights
    df_old = df_old[df_old["cap"] > 0]
    cell_old = df_old.groupby(["y", "x"])["cap"].sum().reset_index()
    
    old_y_idx = cell_old["y"].values
    old_x_idx = cell_old["x"].values
    total_cap = cell_old["cap"].sum()
    if total_cap <= 0:
        print("Error: No operating farm capacity found for Germany. Cannot recover distribution.")
        sys.exit(1)
        
    old_weights = cell_old["cap"].values / total_cap

    # 3. Extract Total Distributed PV from existing grid using Old Weights
    print("Recovering total distributed PV time series...")
    
    # Read the distributed pv grid (3GB float32 usually)
    dist_grid = ds["pv_power_mw_distributed"].values
    
    # Extract values at old farm locations: Shape (T, N_cells)
    vals_old = dist_grid[:, old_y_idx, old_x_idx]
    
    # Logic: vals_old[:, i] ~= Total_Dist_DE[:] * old_weights[i]
    # Ratio = vals_old / old_weights. 
    # Use median across spatial dimension to be robust against overlaps with other countries.
    ratios = vals_old / old_weights[None, :]
    total_de_series = np.median(ratios, axis=1) # Shape (T,)
    
    # Simple check for plausibility
    # If total_de_series is all zeros, maybe no distributed PV generated?
    if np.max(total_de_series) == 0:
        print("Warning: Recovered distributed PV series is all zero.")

    # 4. Remove Old Values
    print(f"Subtracting old distribution from {len(old_y_idx)} cells...")
    # Calculate exactly what the fallback would have put there
    # Cast to float32 to match grid
    delta_old = (total_de_series[:, None] * old_weights[None, :]).astype(np.float32)
    dist_grid[:, old_y_idx, old_x_idx] -= delta_old
    
    # Ensure no negative values from float precision issues (safe for PV)
    # dist_grid = np.maximum(dist_grid, 0.0) # Optional safer step

    # 5. Calculate NEW weights (Population)
    print("Calculating new population weights...")
    if not pop_tif.exists():
        print(f"Error: Population TIF not found: {pop_tif}")
        sys.exit(1)
        
    with rasterio.open(pop_tif) as src:
        arr = src.read(1, masked=True)
        data = np.asarray(arr.filled(0.0), dtype=np.float64)
        valid = (data > 0)
        r, c = np.where(valid)
        w_raw = data[r, c]
        lon_geo, lat_geo = rasterio.transform.xy(src.transform, r, c, offset='center')
    
    new_y, new_x = indexer.map_points(np.array(lat_geo), np.array(lon_geo))
    
    df_new = pd.DataFrame({"y": new_y, "x": new_x, "w": w_raw})
    cell_new = df_new.groupby(["y", "x"])["w"].sum().reset_index()
    
    new_y_idx = cell_new["y"].values
    new_x_idx = cell_new["x"].values
    new_weights = cell_new["w"].values / cell_new["w"].sum()
    
    print(f"Adding new distribution to {len(new_y_idx)} cells...")
    delta_new = (total_de_series[:, None] * new_weights[None, :]).astype(np.float32)
    dist_grid[:, new_y_idx, new_x_idx] += delta_new
    
    # 6. Update and Save
    print("Updating dataset...")
    ds["pv_power_mw_distributed"].values = dist_grid
    
    # Append history
    ds.attrs["history"] = str(ds.attrs.get("history", "")) + f"; {datetime.datetime.now().isoformat()} Fixed Germany PV distribution from farm-fallback to population."
    
    # Create temp output file
    temp_out = grid_file.with_name(grid_file.name.replace(".nc", "_fixed.nc"))
    print(f"Saving to {temp_out}...")
    
    comp = dict(zlib=True, complevel=4)
    encoding = {var: comp for var in ds.data_vars}
    
    ds.to_netcdf(temp_out, engine="h5netcdf", encoding=encoding)
    ds.close()
    
    print("Done.")

if __name__ == "__main__":
    main()
