# CERFRES — physics-based modeling framework for farm-level renewable energy generation in Europe

CERFRES is a framework for simulating high-resolution, hourly timeseries of Solar PV, Onshore Wind, and Offshore Wind power generation across Europe. The model maps individual power plant locations to a high-resolution weather grid, calculates physical power output from local weather conditions, and derives monthly correction factors against historical generation data. The published series are uncalibrated.

## Installation

### Requirements

Python 3.10 or later is recommended. Install all dependencies with:

```bash
pip install -r requirements.txt
```

Packages: `numpy`, `pandas`, `xarray`, `scipy`, `pvlib`, `turbine_models`, `rasterio`, `h5netcdf`, `joblib`, `tqdm`.

## Data Requirements

The scripts use three external datasets that must be downloaded separately. All paths are configured in `config.py` (see [Configuration](#configuration) below).

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
└── highres-renewable-dataset/uncalibrated-v1.2/   # Output root (created automatically)
    ├── country-aggregated-production/
    ├── per-farm-production/
    └── correction_factors/
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
| `--out-dir-factors` | `config.FACTOR_OUTPUT_DIR` | Output directory for correction factors |
| `--factor-set` | `config.FACTOR_SET_DIR` | Complete factor set read for fallback months (before 2015, UK after May 2021). The run stops with an error if it is incomplete. |

## Project Structure

```
CERFRES/
├── config.py                              # Data path configuration (edit DATA_ROOT here)
├── functions.py                           # Shared utility functions (turbine mapping, wind/PV physics)
├── factor_history.py                      # Factor status values and the historical fallback
├── requirements.txt                       # Python dependencies
├── CHANGELOG.md                           # Changes and known issues per release
├── scripts/
│   ├── weather_energy_monthly.py          # Main script: runs the model for one month
│   ├── validate_offshore_wind_output.py   # Validates offshore wind output files
│   ├── build_factor_qa.py                 # QA tables of the factors, from series and ENTSO-E files
│   ├── regenerate_factors.py              # Rewrites factor files without simulating
│   ├── regenerate_distributed_grid.py     # Rewrites grid files without simulating
│   ├── verify_release.py                  # Compares a new dataset with the previous one
│   ├── rule1_checksums.py                 # Checksums of the protected grid variables
│   ├── build_release_archives.py          # Builds the yearly zips
│   └── publish_zenodo.py                  # Creates a new Zenodo version
├── notebooks/
│   ├── complementarity_analysis.ipynb     # Analysis of wind/solar complementarity across Europe
│   └── validation.ipynb                   # Model validation against ENTSO-E actual generation
├── docs/
│   └── zenodo_description_v1.2.0.html     # Dataset description for the Zenodo record
└── tests/                                 # Run with: python -m pytest tests
```

## Output Format

### Country series

`{mm}_{year}_pv_wind_country_timeseries.nc` has dimensions `(time, area)`. All variables are in MW and **uncalibrated**: no correction factor has been applied to them.

| Variable | Fleet |
|---|---|
| `pv_power_mw` | As-built, including distributed PV |
| `pv_power_mw_2025` | Fixed 2025 fleet, including distributed PV |
| `wind_power_mw` | As-built |
| `wind_power_mw_2025` | Fixed 2025 fleet |

### Grid files

`{mm}_{year}_pv_wind_grid.nc` has dimensions `(time, y, x)`. All variables are in MW and describe the **fixed 2025 fleet** in every year, so differences between years come from the weather.

| Variable | Content |
|---|---|
| `wind_power_mw_onshore` | Onshore wind |
| `wind_power_mw_offshore` | Offshore wind |
| `pv_power_mw` | Geo-located PV farms |
| `pv_power_mw_distributed` | Distributed PV |

For each area and hour, `pv_power_mw` plus `pv_power_mw_distributed` adds up to `pv_power_mw_2025`. Grid-wide this holds within 5 MW or 0.01 %, whichever is larger; the difference comes from float32 storage. It cannot be checked cell by cell for a single zone:

- Zones in Denmark and Sweden share their country's population weights, so a zone's distributed output is spread over the whole country.
- Cells near a border can hold output from both countries.

There is no as-built distributed grid. Use the country series for the as-built fleet.

### Correction factors

`correction_factors/{year}/{mm}_{year}_pv_wind_country_factors.csv` has the columns `Area`, `PV_Factor`, `Wind_Factor`, `PV_Status` and `Wind_Status`. In the yearly zips, the months are joined in order without a month column, with 47 rows per month.

| Status | Meaning | Value |
|---|---|---|
| `observed` | Calculated from ENTSO-E generation and the as-built series | The factor |
| `historical_fallback` | No usable ENTSO-E data for this month; recency-weighted mean of the area's `observed` factors for the same calendar month | The fallback |
| `no_observation` | ENTSO-E has too little data for this month, and for fallback months no `observed` factor exists | Placeholder 1.0; do not treat it as "no bias" |
| `no_modelled_fleet` | The modelled as-built fleet is empty | Placeholder 0.0 or 1.0; do not apply it, because 0.0 gives zero generation |
| `invalid_observation` | ENTSO-E data exist but do not describe the area's generation | Calculated factor; do not use it |

Observation windows run from January 2015 to December 2025, except for the UK. ENTSO-E has no complete per-type UK generation after May 2021, so all UK factors from June 2021 are `historical_fallback`, built from January 2015 to May 2021.

### Using the factors

- **Factors belong to the as-built fleet.** They are calibrated on the as-built series and do not transfer to the `_2025` fleet.
- **Factors absorb capacity gaps as well as bias.** A factor near 1 does not mean the output per MW is right. It can be a capacity gap cancelling a per-MW bias.
- **Uncalibrated series divided by capacity are not observed capacity factors.** For 2024:

| Wind, 2024 | Modelled as-built output over modelled capacity | ENTSO-E generation over ENTSO-E capacity |
|---|---|---|
| Germany | 43 % | 23 % |
| Netherlands | 59 % | 22 % |

- **No wake loss through `wake_loss_factor`.** The wind model sets `wake_loss_factor=1.0`, a multiplier on farm power, so no wake loss is applied through that factor.
- **Factors do not always reproduce the series' energy.** See [Known issues](#known-issues).
- **Check the QA table before using a factor.** `qa/factor_qa_annual.csv` lists factor, modelled energy, ENTSO-E energy and as-built capacity per area, technology and year, with implausible values flagged.

## Known Issues

Details are in [CHANGELOG.md](CHANGELOG.md).

- **Factor and series come from different runs.** The published observed factors predate the published series. Where the distributed PV inputs of the two runs differ, multiplying a series by its factor does not reproduce ENTSO-E energy. For PV this overshoots by a median of 3.95 times in Switzerland, 2.45 in Finland, 1.80 in Italy, 1.47 in the UK, 1.34 in Greece, 1.18 in France, 1.17 in Portugal, 1.15 in Germany, 1.11 in Denmark and 1.07 in Austria. For NO1 wind it is 1.07. The QA column `published_over_series_factor` holds the ratio for each area and year.
- **Wind time axis.** CERRA wind `valid_time` is 2 hours after the file's `time` coordinate, and wind series correlate best with ENTSO-E when shifted later by 1–2 hours. PV is not affected.
- **Missing distributed PV.** 21 modelled countries have no row in the GEM distributed tracker, including Belgium, Ireland, Norway and Romania. Their distributed output is zero and their factors absorb the gap.
- **Luxembourg and Kosovo PV metadata.** Their time series cannot be reproduced correctly from the tracker. All 45 Luxembourg farms have no start year, so the as-built series is zero. All three operating Kosovo farms (16.9 MW) are also listed under Serbia, so they are counted in both countries and twice in the grid.
- **Cell sums per country.** Border cells also hold a neighbour's output, so a sum over one country's cells can exceed its series (24 % at most in Luxembourg). Use the country series for national totals.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
