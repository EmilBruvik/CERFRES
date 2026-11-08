# Changelog

## 1.2.0 (code: November 2026; dataset DOI pending)

This release changes `pv_power_mw_distributed` and the correction factors. These data are unchanged:

- `wind_power_mw_onshore`, `wind_power_mw_offshore` and `pv_power_mw` in the grid files, whose compressed chunks are copied byte for byte;
- all four variables in the country-series files;
- the power models and the farm metadata.

### Fixed

- **Observed factors now match the series.** The factors published with v1.1 in `correction_factors/` came from an earlier run (February–March 2026) than the series (April 2026), so multiplying a series by its factor did not reproduce ENTSO-E energy.
  - v1.2 takes its observed factors from the set that the April run wrote next to the series (`country-aggregated-production/{year}/correction_factors/` in v1.1).
  - Recomputing factors from the series and ENTSO-E reproduces all 7601 measured values of this set but one: Croatia wind in February 2025, by 0.15 %, which is probably a later ENTSO-E revision.
  - 6359 of the 12 298 observed-period values change. Median ratio of the v1.1 factor to the v1.2 factor: Switzerland PV 3.95, Finland 2.46, Italy 1.80, UK 1.47, Greece 1.34, France 1.18, Portugal 1.17, Germany 1.15, Denmark 1.11, Austria 1.07; NO1 wind 1.07. Other wind factors change by a few percent, at most 18 %.
  - Which values are 0.0 or 1.0 is the same in both sets, so the status of every row is unaffected.
- **Historical fallback factors.** The old function read whichever factor files existed when a month was simulated, so results depended on run order, and it used earlier fallback values as inputs.
  - Fallback factors now come only from `observed` rows of one fixed, complete factor set, and the code raises an error if that set is incomplete.
  - Each area uses its own observation window: the UK from January 2015 to May 2021, and all others from January 2015 to December 2025.
  - UK wind after May 2021 falls from 0.54–1.25 to 0.45–0.53, with no step at June 2021. UK PV falls from 0.91–1.19 to 0.53–0.69.
  - Pre-2015 factors now have one value per area and calendar month, instead of up to 20. Belgian PV falls by a factor of about 1.9, to a mean of 8.5. Every changed value is in `qa/factor_changes.csv`.
- **Distributed PV grid.** The residual subtracted the fixed 2025 farms from the as-built total, so the variable mixed two fleets and grew over time. It now uses the fixed-fleet total, so `pv_power_mw + pv_power_mw_distributed` equals `pv_power_mw_2025` in every year. Mean output over all areas in July rises from 1.44 GW to 41.5 GW in 2015, and from 23.3 GW to 40.0 GW in 2024.
- **`note` attribute of the country series.** It claimed that a calibrated factor was applied. No factor is applied to any series.
- **`tests/test_farm_timeseries.py`** pointed at a path that does not exist.

### Added

- `PV_Status` and `Wind_Status` in the factor files, added after the existing columns.
- `qa/factor_qa_annual.csv` and `qa/factor_qa_scan.csv`, with modelled energy, ENTSO-E energy, capacity and flags.
- `qa/factor_changes.csv`, with the v1.1 and v1.2 value of every factor that changed.
- Regeneration and checking scripts: `build_factor_qa.py`, `regenerate_factors.py`, `regenerate_distributed_grid.py`, `build_release_archives.py`, `verify_release.py`, `rule1_checksums.py`.

### Changed

- `config.py` now writes to `uncalibrated-v1.2/`, so a new run cannot overwrite the previous release.
- Factor files are written to `correction_factors/{year}/`, the layout used in the archives, and no longer under the country-series folder.
- `run_month` needs `--factor-set` for fallback months.

### Observations marked `invalid_observation`

Their values are unchanged, but they are excluded from fallback inputs.

| Area and technology | Period | Evidence |
|---|---|---|
| Netherlands PV | Oct 2018 – Dec 2025 | ENTSO-E reports about 0.5 TWh per year on up to 29 GW of its own installed capacity (0.1–0.4 %). |
| Switzerland PV | Jan 2015 – Dec 2019 | ENTSO-E generation rises 5.7 times from 2019 to 2020, starting in January 2020. |
| Austria PV | Jan 2019 – Dec 2023 | ENTSO-E generation halves in 2019 on flat capacity (4.5–6.9 % in 2019–2022) and steps up in April 2023 and January 2024. |

### Known issues, not changed in this release

- **Wind time axis.** CERRA wind `valid_time` is 2 hours after the file's `time` coordinate in all sampled months. Wind series correlate best with ENTSO-E when shifted later by 1–2 hours, while PV is best at 0 hours.
- **Missing distributed PV.**
  - 21 modelled countries have no row in the GEM distributed tracker: Albania, Belgium, Bosnia and Herzegovina, Bulgaria, Croatia, Cyprus, Estonia, Georgia, Ireland, Kosovo, Latvia, Moldova, Montenegro, North Macedonia, Norway, Romania, Serbia, Slovakia, Slovenia, Ukraine and the Åland Islands.
  - Their distributed output is zero, and their factors absorb the gap. Belgium is the most visible case, with 905 MW modelled against 10.7 GW in ENTSO-E for 2025.
- **Luxembourg PV metadata.** All 45 operating farms (101.1 MW) have no start year in the tracker. The as-built series is therefore zero in every year and no Luxembourg factor can be observed, while the fixed-fleet series uses those farms plus 634 MW of distributed capacity. Its time series cannot be reproduced correctly from this metadata.
- **Kosovo PV metadata.** The tracker lists all three operating Kosovo farms (16.9 MW) a second time under Serbia, with the same capacity and start year and with coordinates within 0.001°. Both countries' series include them, so they are counted twice in the grid and in any total over both countries. Kosovo's cells hold twice its series. Its time series cannot be reproduced correctly from this metadata.
- **Cell sums per country.** The grid total matches the sum of the series in every month, but a sum over one country's cells can exceed that country's series, because border cells also hold a neighbour's output. The monthly excess reaches more than 1 % in 17 countries: Luxembourg 24 %, Belgium 10 %, Finland, Czech Republic and Switzerland 6 %. Kosovo (100 %) and Serbia (16 %) also carry the duplicate farms above. Use the country series for national totals. Results are in `qa/verify_v1.2.0_countries.csv`.
- **Zone weights.** Zones in Denmark and Sweden share their country's population weights, so a zone's distributed output is spread over the whole country.

## 1.1.1

Added the validation extracts. Output data are unchanged from 1.1.0.

## 1.1.0

Uncalibrated output dataset.

## 1.0

First code release.
