import sys
from pathlib import Path
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

YEAR = '2024'
MONTH = 'sep'
MONTH_NUM = 9
month_number = '09'

print(f"Loading dataset for {YEAR}-{MONTH}...", flush=True)

fn = config.CERRA_MULTI_LEVEL_DIR / YEAR / f"cerra_{YEAR}_multi_level_{MONTH}.nc"
ds = xr.open_dataset(fn, engine='netcdf4')
actual_generation_file = pd.read_csv(
    config.ACTUAL_GENERATION_DIR / YEAR / f"{YEAR}_{month_number}_AggregatedGenerationPerType_16.1.B_C_r3.csv",
    sep='\t',
)

print("Dataset loaded successfully.", flush=True)