# CERFRES — High-Resolution European Renewable Energy Generation Dataset

This repository contains the code used to produce CERFRES: a high-resolution, hourly dataset of Solar PV, Onshore Wind, and Offshore Wind power generation across Europe. The model maps individual power plant locations from the Global Energy Monitor asset trackers to a high-resolution weather grid, computes physical power output from local weather conditions, and calibrates the result against historical ENTSO-E generation data.

## Citation

If you use this dataset or code in your research, please cite:

> [Paper under review — citation will be updated upon publication]

## Installation

### Requirements

Python 3.10 or later is recommended. Install all dependencies with:

```bash
pip install -r requirements.txt
```

Key packages: `numpy`, `pandas`, `xarray`, `scipy`, `pvlib`, `turbine_models`, `rasterio`, `h5netcdf`, `joblib`, `tqdm`.

## Data Requirements

The scripts rely on three external datasets that must be downloaded separately. All paths are configured in `config.py` (see [Configuration](#configuration) below).

| Dataset | Description | Download |
|---------|-------------|----------|
| CERRA single-level | Hourly surface variables (irradiance, 10 m wind, temperature, albedo) | [CDS](https://cds.climate.copernicus.eu/datasets/reanalysis-cerra-single-levels) |
| CERRA multi-level | Hourly wind at height levels (100 m wind speed) | [CDS](https://cds.climate.copernicus.eu/datasets/reanalysis-cerra-height-levels) |
| GEM Solar Power Tracker | Asset-level solar PV database | [GEM](https://globalenergymonitor.org/projects/global-solar-power-tracker/download-data/) |
| GEM Wind Power Tracker | Asset-level wind farm database | [GEM](https://globalenergymonitor.org/projects/global-wind-power-tracker/download-data/) |
| ENTSO-E generation | Actual hourly aggregated generation per production type | [ENTSO-E Transparency](https://transparency.entsoe.eu/) |


## Configuration

Open `config.py` and set `DATA_ROOT` to the root of your local data directory:

```python
DATA_ROOT = Path("/path/to/your/data")
```

All other paths (input datasets and output directories) are derived automatically from `DATA_ROOT`. The expected subdirectory layout is:

```
DATA_ROOT/
├── CERRA_single_level/{year}/reanalysis-cerra-single-levels-{month}-{year}-time{n}.nc
├── CERRA_multi_level/{year}/cerra_{year}_multi_level_{month}.nc
├── Solar_data/
│   ├── Global-Solar-Power-Tracker-February-2026.csv
│   ├── Global-Solar-Power-Tracker-February-2026-Distributed.csv
│   └── population_distribution/          # GeoTIFF population rasters per country
├── Wind_data/
│   ├── Global-Wind-Power-Tracker-February-2026.csv
│   └── Global-Wind-Power-Tracker-February-2026-Below_Threshold.csv
├── Actual_Generation/AggregatedGenerationPerType/{year}/{year}_{mm}_AggregatedGenerationPerType_16.1.B_C_r3.csv
└── highres-renewable-dataset/            # Output root (created automatically)
    ├── country-aggregated-production/
    └── per-farm-production/
```

## Usage

### Run one month

```bash
python -u scripts/weather_energy_monthly.py --year 2024 --month 09 --n-jobs-pv 2
```

Produces `{out-dir}/{year}/{mm}_{year}_pv_wind_country_timeseries.nc`.

### Run a full year

```bash
for m in $(seq -w 1 12); do
  python -u scripts/weather_energy_monthly.py --year 2024 --month "$m" --n-jobs-pv 2
done
```

### CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--year` | *(required)* | Year to process |
| `--month` | *(required)* | Month number (01–12) |
| `--n-jobs-pv` | `8` | Parallel jobs for PV calculation |
| `--out-dir` | `config.OUTPUT_DIR` | Output directory for aggregated country results |
| `--out-dir-farm` | `config.OUTPUT_DIR_FARM` | Output directory for gridded spatial results |

## Project Structure

```
CERFRES/
├── config.py                              # Data path configuration (edit DATA_ROOT here)
├── functions.py                           # Shared utility functions (turbine mapping, wind/PV physics)
├── requirements.txt                       # Python dependencies
├── scripts/
│   ├── weather_energy_monthly.py          # Main script — runs the model for one month
│   ├── wind_turbine_type_histogram.py     # Analysis: histogram of mapped turbine model types
│   └── validate_offshore_wind_output.py   # Validates offshore wind output files
├── notebooks/
│   ├── complementarity_analysis.ipynb     # Analysis of wind/solar complementarity across Europe
│   └── validation.ipynb                   # Model validation against ENTSO-E actual generation
└── test_farm_timeseries.py                # Validation tests for the per-farm feature
```

## Output Format

The main output is a NetCDF file per month with dimensions `(time, country)` containing:

- `pv_power_mw` — Solar PV generation (MW), calibrated
- `wind_power_mw` — Wind generation (MW), calibrated

A spatial grid output is also written per month (`{mm}_{year}_pv_wind_grid.nc`) with dimensions `(time, y, x)`, containing separate variables for onshore wind, offshore wind, utility-scale PV, and distributed PV.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
