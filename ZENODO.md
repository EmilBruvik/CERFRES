# Zenodo Upload Guide

This document describes how to upload the CERFRES dataset to Zenodo.
The metadata in `.zenodo.json` matches what should be entered in the Zenodo form.

---

## Title

**CERFRES: Calibrated High-Resolution European Renewable Energy Generation Dataset**

---

## Description (paste into Zenodo form)

CERFRES is an hourly dataset of power generation for Solar PV, Onshore Wind, and Offshore Wind across 44 European countries and bidding zones. Generation timeseries are computed by mapping individual power plant locations from the Global Energy Monitor (GEM) Solar and Wind Power Trackers to the Copernicus European Regional Reanalysis (CERRA) high-resolution weather grid. Solar PV output is calculated using the PVWatts model (via pvlib-python) and wind power using turbine-type-specific power curves matched to installation year and technology type. Modelled generation is calibrated against actual generation reported on the ENTSO-E Transparency Platform using a per-country/zone calibration factor.

The dataset is provided in two complementary NetCDF formats per month:
1. **Country-aggregated timeseries** (dimensions: time × country/bidding zone) — four variables: as-built and 2025-fleet-scenario estimates for both PV and wind
2. **Spatially gridded output** (dimensions: time × y × x) — separating onshore wind, offshore wind, utility-scale PV, and population-weighted distributed PV

All variables are in megawatts (MW) at hourly temporal resolution.

The 44 covered areas include 33 European countries and sub-national bidding zones for Norway (NO1–NO5), Sweden (SE1–SE4), and Denmark (DK1–DK2). Distributed PV is spatially allocated using WorldPop 2026 country-level population rasters. The code used to produce this dataset is available at https://github.com/emilbruvik/cerfres.

---

## Metadata Fields

| Field | Value |
|-------|-------|
| **Upload type** | Dataset |
| **Title** | CERFRES: Calibrated High-Resolution European Renewable Energy Generation Dataset |
| **Authors** | Bruvik, Emil — University of Bergen |
| **License** | MIT |
| **Access** | Open Access |
| **Language** | English |
| **Version** | 1.0.0 |

---

## Keywords

```
renewable energy, solar energy, photovoltaic, wind energy, power generation,
Europe, reanalysis, CERRA, ENTSO-E, timeseries, hourly resolution, energy dataset,
calibration, pvlib, high resolution
```

---

## Spatial/Temporal Coverage

- **Spatial coverage**: 44 European countries and bidding zones
  - Countries: AT, AL, BA, BE, BG, CH, CY, CZ, DE, EE, ES, FI, FR, GE, GR, HR, HU, IE, IT, KO, LT, LU, LV, MD, ME, MK, NL, PL, PT, RO, RS, SI, SK, UA, UK
  - Multi-zone countries: NO1–NO5 (Norway), SE1–SE4 (Sweden), DK1–DK2 (Denmark)
- **Temporal resolution**: Hourly
- **Years covered**: [FILL IN — e.g. 2000–2024]

---

## Related Links

- **Code repository**: https://github.com/emilbruvik/cerfres  (relation: *is supplemented by*)
- **Related publication**: [Add DOI when available]  (relation: *is cited by*)

---

## Files to Upload

Organise uploads by year. For each year, upload two files per month:

```
{year}/
├── 01_{year}_pv_wind_country_timeseries.nc   # country-aggregated (time × area)
├── 01_{year}_pv_wind_grid.nc                 # spatial grid (time × y × x)
├── 02_{year}_pv_wind_country_timeseries.nc
├── 02_{year}_pv_wind_grid.nc
...
└── 12_{year}_pv_wind_grid.nc
```

**Recommended**: zip each year into a single archive before uploading:
```bash
zip -r cerfres_2024.zip 2024/
```

---

## Variable Reference

### Country-aggregated file (`*_pv_wind_country_timeseries.nc`)

| Variable | Unit | Description |
|----------|------|-------------|
| `pv_power_mw` | MW | Solar PV — as-built fleet, calibrated |
| `pv_power_mw_2025` | MW | Solar PV — 2025 planned fleet, calibrated |
| `wind_power_mw` | MW | Total wind — as-built fleet, calibrated |
| `wind_power_mw_2025` | MW | Total wind — 2025 planned fleet, calibrated |

### Spatial grid file (`*_pv_wind_grid.nc`)

| Variable | Unit | Description |
|----------|------|-------------|
| `pv_power_mw` | MW | Utility-scale / geolocated solar PV |
| `pv_power_mw_distributed` | MW | Distributed PV, population-weighted |
| `wind_power_mw_onshore` | MW | Onshore wind |
| `wind_power_mw_offshore` | MW | Offshore wind |

---

## Notes for the Zenodo Record

Add the following in the **Notes** field:

> Data produced using the CERFRES modelling framework (https://github.com/emilbruvik/cerfres). Input weather data: CERRA reanalysis (Copernicus Climate Data Store). Asset data: Global Energy Monitor Solar and Wind Power Trackers (February 2026 release). Calibration data: ENTSO-E Transparency Platform. Related publication: under review — citation will be updated upon publication.
