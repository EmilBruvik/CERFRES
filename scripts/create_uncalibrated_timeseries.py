import os
import sys
import pandas as pd
import xarray as xr
import numpy as np
from pathlib import Path

# Setup path so tracking functions resolve out-of-the-box
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from scripts.weather_energy_monthly import (
    MonthlyRunner, countries_tracker, countries_codes, ZONES, _installation_bucket, GridIndexer
)

DATA_ROOT = Path("/Data/gfi/vindenergi/nab015/highres-renewable-dataset")
YEAR = 2024

def process_aggregated():
    aggregated_dir = DATA_ROOT / "country-aggregated-production" / str(YEAR)
    factors_dir = aggregated_dir / "correction_factors"
    out_dir = DATA_ROOT / "uncalibrated" / "country-aggregated-production" / str(YEAR)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    for month in range(1, 13):
        calibrated_nc = aggregated_dir / f"{month:02d}_{YEAR}_pv_wind_country_timeseries.nc"
        factors_csv = factors_dir / f"{month:02d}_{YEAR}_pv_wind_country_factors.csv"

        if not calibrated_nc.exists() or not factors_csv.exists():
            continue

        uncalibrated_nc = out_dir / calibrated_nc.name

        print(f"Uncalibrating aggregated timeseries {month:02d}...")
        ds = xr.open_dataset(calibrated_nc)
        factors_df = pd.read_csv(factors_csv, index_col=0)

        factors_da = xr.DataArray(
            np.ones((len(ds.country), 2)),
            coords={"country": ds.country.values, "technology": ["Wind", "PV"]},
            dims=["country", "technology"]
        )

        for country in ds.country.values:
            if country in factors_df.index:
                row = factors_df.loc[country]
                w_f = row["Wind_Factor"]
                p_f = row["PV_Factor"]
                if not pd.isna(w_f) and w_f > 0:
                    factors_da.loc[country, "Wind"] = w_f
                if not pd.isna(p_f) and p_f > 0:
                    factors_da.loc[country, "PV"] = p_f

        ds_uncal = ds / factors_da
        ds_uncal.to_netcdf(uncalibrated_nc)
        ds_uncal.close()
        ds.close()
        print(f"Saved {uncalibrated_nc}")

def process_farm():
    print("Preparing grid mapping instances...")
    runner = MonthlyRunner(DATA_ROOT, DATA_ROOT, n_jobs_pv=1)
    
    farm_dir = DATA_ROOT / "per-farm-production" / str(YEAR)
    factors_dir = DATA_ROOT / "country-aggregated-production" / str(YEAR) / "correction_factors"
    out_dir = DATA_ROOT / "uncalibrated" / "per-farm-production" / str(YEAR)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    for month in range(1, 13):
        nc_file = farm_dir / f"{month:02d}_{YEAR}_pv_wind_grid.nc"
        factors_csv = factors_dir / f"{month:02d}_{YEAR}_pv_wind_country_factors.csv"
        
        if not nc_file.exists() or not factors_csv.exists():
            continue
            
        print(f"Uncalibrating farm grid {nc_file.name}...")
        
        # Load grid coordinate mappings.
        ds = xr.open_dataset(nc_file)
        indexer = GridIndexer(ds['latitude'].values, ds['longitude'].values)
        
        factors_df = pd.read_csv(factors_csv)

        pv_f_grid = np.ones((ds.sizes['y'], ds.sizes['x']), dtype=np.float32)
        pv_dist_f_grid = np.ones((ds.sizes['y'], ds.sizes['x']), dtype=np.float32)
        wind_on_f_grid = np.ones((ds.sizes['y'], ds.sizes['x']), dtype=np.float32)
        wind_off_f_grid = np.ones((ds.sizes['y'], ds.sizes['x']), dtype=np.float32)

        for country, code in zip(countries_tracker, countries_codes):
            row = factors_df[factors_df['Area'] == code]
            if row.empty: continue
            
            pv_f = float(row['PV_Factor'].iloc[0])
            w_f = float(row['Wind_Factor'].iloc[0])
            
            if pd.isna(pv_f) or pv_f == 0: pv_f = 1.0
            if pd.isna(w_f) or w_f == 0: w_f = 1.0

            # Wind
            df_w = runner.wind.df[runner.wind.df["Country/Area"] == country].copy()
            if code in ZONES:
                if code.startswith('DK'):
                    df_w = df_w[df_w['Location'].str.contains('Bormholm|Bornholm', case=False, na=False) == (code == 'DK2')]
                elif code.startswith('IT'):
                    df_w = df_w[df_w['Project Name'].str.contains('Sicily|Sardinia', case=False, na=False) == (code != 'IT')]
            
            df_w = df_w[df_w["Status"] == "operating"]
            start_yr_w = pd.to_numeric(df_w["Start year"], errors='coerce')
            df_w = df_w[start_yr_w.isna() | (start_yr_w <= YEAR)]
            
            lat_w = pd.to_numeric(df_w["Latitude"], errors='coerce')
            lon_w = pd.to_numeric(df_w["Longitude"], errors='coerce')
            valid_w = ~(lat_w.isna() | lon_w.isna())
            
            if valid_w.any():
                y_i, x_i = indexer.map_points(lat_w[valid_w].values, lon_w[valid_w].values)
                for i, r in df_w[valid_w].reset_index(drop=True).iterrows():
                    if _installation_bucket(r["Installation Type"]) == 'offshore':
                        wind_off_f_grid[y_i[i], x_i[i]] = w_f
                    else:
                        wind_on_f_grid[y_i[i], x_i[i]] = w_f

            # PV
            df_pv = runner.pv.df_main[runner.pv.df_main["Country/Area"] == country].copy()
            if code in ZONES:
                if code.startswith('DK'):
                    df_pv = df_pv[df_pv['Location'].str.contains('Bormholm|Bornholm', case=False, na=False) == (code == 'DK2')]
                elif code.startswith('IT'):
                    df_pv = df_pv[df_pv['Project Name'].str.contains('Sicily|Sardinia', case=False, na=False) == (code != 'IT')]

            df_pv = df_pv[df_pv["Status"] == "operating"]
            start_yr_pv = pd.to_numeric(df_pv["Start year"], errors='coerce')
            df_pv = df_pv[start_yr_pv.isna() | (start_yr_pv <= YEAR)]

            lat_pv = pd.to_numeric(df_pv["Latitude"], errors='coerce')
            lon_pv = pd.to_numeric(df_pv["Longitude"], errors='coerce')
            valid_pv = ~(lat_pv.isna() | lon_pv.isna())

            if valid_pv.any():
                y_i, x_i = indexer.map_points(lat_pv[valid_pv].values, lon_pv[valid_pv].values)
                pv_f_grid[y_i, x_i] = pv_f

            pop_w = runner._country_population_cell_weights(country, indexer)
            if pop_w is not None:
                pv_dist_f_grid[pop_w[0], pop_w[1]] = pv_f
                
        ds_uncal = ds.copy()
        
        if 'wind_power_mw_onshore' in ds_uncal:
            ds_uncal['wind_power_mw_onshore'] = ds_uncal['wind_power_mw_onshore'] / wind_on_f_grid
        if 'wind_power_mw_offshore' in ds_uncal:
            ds_uncal['wind_power_mw_offshore'] = ds_uncal['wind_power_mw_offshore'] / wind_off_f_grid
        if 'pv_power_mw' in ds_uncal:
            ds_uncal['pv_power_mw'] = ds_uncal['pv_power_mw'] / pv_f_grid
        if 'pv_power_mw_distributed' in ds_uncal:
            ds_uncal['pv_power_mw_distributed'] = ds_uncal['pv_power_mw_distributed'] / pv_dist_f_grid
            
        uncal_path = out_dir / nc_file.name
        ds_uncal.to_netcdf(uncal_path)
        ds.close()
        ds_uncal.close()
        print(f"Saved {uncal_path}")

if __name__ == "__main__":
    process_aggregated()
    process_farm()
