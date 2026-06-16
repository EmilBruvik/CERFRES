"""
set DATA_ROOT to the root of your local data directory.
All dataset paths are derived from DATA_ROOT.
"""

from pathlib import Path

#set this to the directory that contains your CERRA, Solar_data, Wind_data,
DATA_ROOT = Path("/Data/gfi/vindenergi/nab015")

#input: CERRA weather reanalysis
CERRA_MULTI_LEVEL_DIR  = DATA_ROOT / "CERRA_multi_level"   # {year}/cerra_{year}_multi_level_{month}.nc
CERRA_SINGLE_LEVEL_DIR = DATA_ROOT / "CERRA_single_level"  # {year}/reanalysis-cerra-single-levels-{month}-{year}-time{n}.nc

#input: Global Energy Monitor asset trackers
SOLAR_TRACKER_CSV             = DATA_ROOT / "Solar_data" / "Global-Solar-Power-Tracker-February-2026.csv"
SOLAR_TRACKER_DISTRIBUTED_CSV = DATA_ROOT / "Solar_data" / "Global-Solar-Power-Tracker-February-2026-Distributed.csv"
SOLAR_POPULATION_DIR          = DATA_ROOT / "Solar_data" / "population_distribution"
WIND_TRACKER_CSV       = DATA_ROOT / "Wind_data" / "Global-Wind-Power-Tracker-February-2026.csv"
WIND_TRACKER_BELOW_CSV = DATA_ROOT / "Wind_data" / "Global-Wind-Power-Tracker-February-2026-Below_Threshold.csv"

#input: ENTSO-E actual generation
ACTUAL_GENERATION_DIR = DATA_ROOT / "Actual_Generation" / "AggregatedGenerationPerType"

#output directories
# OUTPUT_DIR      = DATA_ROOT / "highres-renewable-dataset" / "country-aggregated-production"
# OUTPUT_DIR_FARM = DATA_ROOT / "highres-renewable-dataset" / "per-farm-production"
# FIGURES_DIR     = DATA_ROOT / "figures"
OUTPUT_DIR      = DATA_ROOT / "highres-renewable-dataset" / "uncalibrated" / "country-aggregated-production"
OUTPUT_DIR_FARM = DATA_ROOT / "highres-renewable-dataset" / "uncalibrated" / "per-farm-production"
FIGURES_DIR     = DATA_ROOT / "figures"
