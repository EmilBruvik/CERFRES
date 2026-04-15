"""
CERFRES configuration — set DATA_ROOT to the root of your local data directory.

All dataset paths are derived from DATA_ROOT so this is the only value
you need to change to run the scripts on a new system.
"""

from pathlib import Path

# ── User configuration ────────────────────────────────────────────────────────
# Set this to the directory that contains your CERRA, Solar_data, Wind_data,
# Actual_Generation, and output folders.
DATA_ROOT = Path("/Data/gfi/vindenergi/nab015")
# ─────────────────────────────────────────────────────────────────────────────

# Input: CERRA weather reanalysis
# Download via scripts/CERRA_multiple_level_download_all.py or the CDS API.
CERRA_MULTI_LEVEL_DIR  = DATA_ROOT / "CERRA_multi_level"   # {year}/cerra_{year}_multi_level_{month}.nc
CERRA_SINGLE_LEVEL_DIR = DATA_ROOT / "CERRA_single_level"  # {year}/reanalysis-cerra-single-levels-{month}-{year}-time{n}.nc

# Input: Global Energy Monitor asset trackers
# Download from https://globalenergymonitor.org/projects/global-solar-power-tracker/download-data/
# and          https://globalenergymonitor.org/projects/global-wind-power-tracker/download-data/
SOLAR_TRACKER_CSV             = DATA_ROOT / "Solar_data" / "Global-Solar-Power-Tracker-February-2026.csv"
SOLAR_TRACKER_DISTRIBUTED_CSV = DATA_ROOT / "Solar_data" / "Global-Solar-Power-Tracker-February-2026-Distributed.csv"
SOLAR_POPULATION_DIR          = DATA_ROOT / "Solar_data" / "population_distribution"

WIND_TRACKER_CSV       = DATA_ROOT / "Wind_data" / "Global-Wind-Power-Tracker-February-2026.csv"
WIND_TRACKER_BELOW_CSV = DATA_ROOT / "Wind_data" / "Global-Wind-Power-Tracker-February-2026-Below_Threshold.csv"

# Input: ENTSO-E actual generation
# Download from https://transparency.entsoe.eu/
ACTUAL_GENERATION_DIR = DATA_ROOT / "Actual_Generation" / "AggregatedGenerationPerType"

# Output directories
# OUTPUT_DIR      = DATA_ROOT / "highres-renewable-dataset" / "country-aggregated-production"
# OUTPUT_DIR_FARM = DATA_ROOT / "highres-renewable-dataset" / "per-farm-production"
# FIGURES_DIR     = DATA_ROOT / "figures"
OUTPUT_DIR      = DATA_ROOT / "highres-renewable-dataset" / "uncalibrated" / "country-aggregated-production"
OUTPUT_DIR_FARM = DATA_ROOT / "highres-renewable-dataset" / "uncalibrated" / "per-farm-production"
FIGURES_DIR     = DATA_ROOT / "figures"
