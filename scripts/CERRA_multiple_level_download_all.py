import time
import sys
from pathlib import Path

import cdsapi
import os
from calendar import monthrange

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

dataset = "reanalysis-cerra-height-levels"

years = ["1999", 
         "1998", 
         "1997", 
         "1996", 
         "1995"
         ]

months = [
    ("01", "jan"),
    ("02", "feb"),
    ("03", "mar"),
    ("04", "apr"),
    ("05", "may"),
    ("06", "jun"),
    ("07", "jul"),
    ("08", "aug"),
    ("09", "sep"),
    ("10", "oct"),  
    ("11", "nov"),
    ("12", "dec") 
]

def days_in_month(year: str, month: str) -> list[str]:
    """Return zero-padded day strings for the given year/month."""
    num_days = monthrange(int(year), int(month))[1]
    return [f"{day:02d}" for day in range(1, num_days + 1)]

client = cdsapi.Client()

for year in years:
    for month_num, month_name in months:
        request = {
            "variable": [
                # "temperature",
                # "wind_direction",
                "wind_speed"
        ],
        "height_level": [
            "30_m",
            "50_m",
            "75_m",
            "100_m",
            "150_m",
            "200_m"
        ],
        "data_type": ["reanalysis"],
        "product_type": ["forecast"],
        "year": [year],
        "month": [month_num],
        "day": days_in_month(year, month_num),
        "time": [
            "00:00", "03:00", "06:00",
            "09:00", "12:00", "15:00",
            "18:00", "21:00"
        ],
        "leadtime_hour": [
            "3",
            "4",
            "5"
        ],
        "data_format": "netcdf"
    }

        target_folder = config.CERRA_MULTI_LEVEL_DIR / year
        
        os.makedirs(target_folder, exist_ok=True)
        print(f"Requesting data for {month_name} {year}...")
        filename = target_folder / f"cerra_{year}_multi_level_{month_name}.nc"
        
        retry_counter  = 0
        while True:
            try:
                client.retrieve(dataset, request, str(filename)) 
                break
            except Exception as e:
                print(f"Error encountered: {e}")
                if retry_counter >= 1:
                    print(f"Failed to retrieve data for {month_name} {year} after 2 attempts. Skipping to next month.")
                    break
                retry_counter += 1
                print(f"Retrying request for {month_name} {year} in 30 minutes... (Attempt {retry_counter})")
                time.sleep(1800)