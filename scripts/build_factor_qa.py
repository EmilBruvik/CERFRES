#!/usr/bin/env python3
"""QA table of the correction factors, built from existing series and ENTSO-E files.

scan:   one row per area, technology and month with modelled energy, ENTSO-E energy and the
        factor recomputed with the same code as the simulation. No weather data are needed.
annual: one row per area, technology and year, with implausible values flagged.
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import factor_history
import functions
import weather_energy_monthly as wem

YEARS = range(1995, 2026)

# An area-year is flagged outside these limits.
FACTOR_HIGH = 3.0
FACTOR_LOW = 0.2
FACTOR_STEP_RATIO = 3.0
MIN_ENTSOE_HOUR_SHARE = 0.5
# Lower limits for ENTSO-E generation over ENTSO-E's own installed capacity. These are below
# typical European annual capacity factors, so falling under them can point to under-reporting.
TSO_CF_LOW = {"PV": 0.07, "Wind": 0.10}
# Published factor over the factor that reproduces the published series.
SERIES_RATIO_TOLERANCE = 1.05


def read_wind_valid_time(year: int, month: int) -> np.ndarray:
    name = dict(wem.MONTHS)[f"{month:02d}"]
    path = config.CERRA_MULTI_LEVEL_DIR / str(year) / f"cerra_{year}_multi_level_{name}.nc"
    with xr.open_dataset(path, engine="h5netcdf") as src:
        return src["valid_time"].values


def scan_month(task: tuple[Path, int, int]) -> pd.DataFrame:
    series_root, year, month = task
    path = series_root / str(year) / f"{month:02d}_{year}_pv_wind_country_timeseries.nc"
    with xr.open_dataset(path, engine="h5netcdf") as src:
        src.load()

    actual_file = None
    loader = None
    if year >= factor_history.FIRST_OBSERVED_MONTH[0]:
        loader = wem.ActualGenerationLoader(functions.get_timezone_mapping(), functions.get_area_code_mapping())
        actual_file = loader.load_month_file(str(year), f"{month:02d}")

    time_vals = src["time"].values
    wind_time = time_vals
    wind_offset_hours = np.nan
    if actual_file is not None:
        # WindCalculator compares wind with ENTSO-E one hour before CERRA valid_time.
        wind_valid_time = read_wind_valid_time(year, month)
        wind_time = pd.to_datetime(wind_valid_time) - pd.Timedelta(hours=1)
        wind_offset_hours = float((wind_valid_time[0] - time_vals[0]) / np.timedelta64(1, "h"))
    rows = []
    for area_index, area in enumerate(src["area"].values):
        area = str(area)
        for technology, as_built_var, fleet_var, model_time, load in (
            ("PV", "pv_power_mw", "pv_power_mw_2025", time_vals, "solar_series_mw"),
            ("Wind", "wind_power_mw", "wind_power_mw_2025", wind_time, "wind_series_mw"),
        ):
            model = src[as_built_var].values[:, area_index]
            row = {
                "Area": area,
                "Technology": technology,
                "Year": year,
                "Month": month,
                "hours": len(model),
                "modelled_asbuilt_mwh": float(np.nansum(model)),
                "modelled_2025_mwh": float(np.nansum(src[fleet_var].values[:, area_index])),
                "entsoe_mwh": np.nan,
                "entsoe_hours_above_1mw": 0,
                "factor_recomputed": np.nan,
                "wind_valid_time_offset_hours": wind_offset_hours if technology == "Wind" else np.nan,
            }
            if actual_file is not None:
                actual = getattr(loader, load)(actual_file, area)
                row["entsoe_mwh"] = float(actual.sum()) if len(actual) else 0.0
                row["entsoe_hours_above_1mw"] = int((actual > 1.0).sum()) if len(actual) else 0
                if float(row["entsoe_mwh"]) <= 1.0:
                    row["factor_recomputed"] = 1.0
                else:
                    row["factor_recomputed"] = float(wem.PVCalculator._factor_from_asbuilt(model, model_time, actual))
            rows.append(row)
    return pd.DataFrame(rows)


def run_scan(args: argparse.Namespace) -> None:
    tasks = [(args.series_root, year, month) for year in YEARS for month in range(1, 13)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        frames = list(pool.map(scan_month, tasks))
    table = pd.concat(frames, ignore_index=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)
    print(f"Wrote {len(table)} rows to {args.out}", flush=True)


def asbuilt_capacity_table() -> pd.DataFrame:
    """Modelled as-built capacity per area, technology and year, including distributed PV."""
    pv_main = wem._read_tracker_csv(config.SOLAR_TRACKER_CSV)
    pv_distributed = wem._read_tracker_csv(config.SOLAR_TRACKER_DISTRIBUTED_CSV)
    wind_all = pd.concat(
        [wem._read_tracker_csv(config.WIND_TRACKER_CSV), wem._read_tracker_csv(config.WIND_TRACKER_BELOW_CSV)],
        ignore_index=True,
    )
    rows = []
    for country, area in zip(wem.countries_tracker, wem.countries_codes):
        fleet, scale = wem.select_pv_fleet(pv_main, pv_distributed, country, area)
        pv_cap = pd.to_numeric(fleet.get("Capacity (MW)", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        pv_start = pd.to_numeric(fleet.get("Start year", pd.Series(dtype=float)), errors="coerce")

        wind = wem._filter_to_area(wind_all[wind_all["Country/Area"] == country].copy(), area, wem.LOCATION_COLS_WIND)
        wind = wind[wind["Status"].isin(set(functions.operating_farms(country, "wind")))]
        wind_cap = pd.to_numeric(wind["Capacity (MW)"], errors="coerce").fillna(0.0)
        wind_start = pd.to_numeric(wind["Start year"], errors="coerce")

        for year in YEARS:
            rows.append(
                {
                    "Area": area,
                    "Technology": "PV",
                    "Year": year,
                    "asbuilt_capacity_mw": float(pv_cap[pv_start <= year].sum() * scale),
                }
            )
            rows.append(
                {
                    "Area": area,
                    "Technology": "Wind",
                    "Year": year,
                    "asbuilt_capacity_mw": float(wind_cap[(wind_start >= 1800) & (wind_start <= year)].sum()),
                }
            )
    return pd.DataFrame(rows)


def tso_capacity_table(path: Path | None) -> pd.DataFrame:
    columns = ["Area", "Technology", "Year", "entsoe_installed_mw"]
    if path is None or not path.is_file():
        return pd.DataFrame(columns=columns)
    table = pd.read_csv(path, sep="\t")
    name_by_area = functions.get_area_code_mapping()
    rows = []
    for technology, kinds in (("PV", ["Solar"]), ("Wind", ["Wind Onshore", "Wind Offshore"])):
        subset = table[table["ProductionType"].isin(kinds)]
        for area in wem.countries_codes:
            codes = name_by_area.get(area, [])
            match = subset[subset["AreaCode"].isin(codes)]
            if match.empty:
                continue
            totals = match.groupby(["Year", "AreaCode", "ProductionType"])["AggregatedInstalledCapacity[MW]"].max()
            for year, value in totals.groupby(level="Year").sum().items():
                rows.append({"Area": area, "Technology": technology, "Year": int(year), "entsoe_installed_mw": float(value)})
    return pd.DataFrame(rows, columns=columns)


def read_factor_set(root: Path) -> pd.DataFrame:
    frames = []
    for year in YEARS:
        for month in range(1, 13):
            frame = pd.read_csv(factor_history.factor_file_path(root, year, month))
            for technology, (factor_col, status_col) in factor_history.TECHNOLOGY_COLUMNS.items():
                frames.append(
                    pd.DataFrame(
                        {
                            "Area": frame["Area"],
                            "Technology": technology,
                            "Year": year,
                            "Month": month,
                            "factor": frame[factor_col],
                            "status": frame[status_col],
                        }
                    )
                )
    return pd.concat(frames, ignore_index=True)


def flag_row(row: pd.Series) -> str:
    flags = []
    if row["months_observed"] + row["months_invalid_observation"] == 0:
        return ""
    factor = row["factor_annual"]
    if np.isfinite(factor) and factor > FACTOR_HIGH:
        flags.append("factor_above_3")
    if np.isfinite(factor) and factor < FACTOR_LOW:
        flags.append("factor_below_0.2")
    if row["entsoe_hour_share"] < MIN_ENTSOE_HOUR_SHARE and row["Technology"] == "Wind":
        flags.append("entsoe_mostly_missing")
    if np.isfinite(row["entsoe_cf_tso"]) and row["entsoe_cf_tso"] < TSO_CF_LOW[row["Technology"]]:
        flags.append("low_generation_on_tso_capacity")
    if np.isfinite(row["factor_step"]) and row["factor_step"] > FACTOR_STEP_RATIO:
        flags.append("factor_step_from_previous_year")
    ratio = row["published_over_series_factor"]
    if np.isfinite(ratio) and not 1.0 / SERIES_RATIO_TOLERANCE < ratio < SERIES_RATIO_TOLERANCE:
        flags.append("factor_differs_from_series")
    return ";".join(flags)


def run_annual(args: argparse.Namespace) -> None:
    scan = pd.read_csv(args.scan)
    factors = read_factor_set(args.factor_set)
    merged = scan.merge(factors, on=["Area", "Technology", "Year", "Month"], validate="one_to_one")
    is_measured = merged["status"].isin([factor_history.STATUS_OBSERVED, factor_history.STATUS_INVALID_OBSERVATION])
    merged["published_over_series"] = (merged["factor"] / merged["factor_recomputed"]).where(is_measured)

    keys = ["Area", "Technology", "Year"]
    annual = merged.groupby(keys, sort=False).agg(
        modelled_asbuilt_mwh=("modelled_asbuilt_mwh", "sum"),
        modelled_2025_mwh=("modelled_2025_mwh", "sum"),
        entsoe_mwh=("entsoe_mwh", "sum"),
        hours=("hours", "sum"),
        entsoe_hours=("entsoe_hours_above_1mw", "sum"),
        factor_month_median=("factor", "median"),
        factor_month_min=("factor", "min"),
        factor_month_max=("factor", "max"),
        published_over_series_factor=("published_over_series", "median"),
    ).reset_index()
    for status in factor_history.ALL_STATUSES:
        counts = merged[merged["status"] == status].groupby(keys).size().rename(f"months_{status}")
        annual = annual.merge(counts, on=keys, how="left")
        annual[f"months_{status}"] = annual[f"months_{status}"].fillna(0).astype(int)

    annual = annual.merge(asbuilt_capacity_table(), on=keys, how="left")
    annual = annual.merge(tso_capacity_table(args.tso_capacity), on=keys, how="left")

    annual["entsoe_mwh"] = annual["entsoe_mwh"].where(annual["Year"] >= 2015)
    annual["factor_annual"] = annual["entsoe_mwh"] / annual["modelled_asbuilt_mwh"].where(annual["modelled_asbuilt_mwh"] > 0)
    capacity_hours = (annual["asbuilt_capacity_mw"] * annual["hours"]).where(annual["asbuilt_capacity_mw"] > 0)
    annual["modelled_cf"] = annual["modelled_asbuilt_mwh"] / capacity_hours
    annual["entsoe_cf_on_modelled_capacity"] = annual["entsoe_mwh"] / capacity_hours
    annual["entsoe_cf_tso"] = annual["entsoe_mwh"] / (annual["entsoe_installed_mw"] * annual["hours"]).where(
        annual["entsoe_installed_mw"] > 0
    )
    annual["entsoe_hour_share"] = annual["entsoe_hours"] / annual["hours"]

    annual = annual.sort_values(keys).reset_index(drop=True)
    previous = annual.groupby(["Area", "Technology"])["factor_annual"].shift(1)
    ratio = annual["factor_annual"] / previous
    annual["factor_step"] = np.maximum(ratio, 1.0 / ratio.where(ratio > 0))
    annual["flags"] = annual.apply(flag_row, axis=1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    annual.to_csv(args.out, index=False)
    print(f"Wrote {len(annual)} rows to {args.out}; flagged: {(annual['flags'] != '').sum()}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--series-root", type=Path, required=True)
    scan.add_argument("--out", type=Path, required=True)
    scan.add_argument("--workers", type=int, default=4)
    scan.set_defaults(func=run_scan)

    annual = sub.add_parser("annual")
    annual.add_argument("--scan", type=Path, required=True)
    annual.add_argument("--factor-set", type=Path, required=True)
    annual.add_argument("--tso-capacity", type=Path, default=None)
    annual.add_argument("--out", type=Path, required=True)
    annual.set_defaults(func=run_annual)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
