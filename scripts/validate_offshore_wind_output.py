#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr


OUTPUT_FILE = Path(
    "/Data/gfi/vindenergi/nab015/Wind_data/havvind_identifiserteomrader_2023f/"
    "havvind_identifiserteomrader_output/offshore_all_sites_wind_timeseries_2024_1000MW.nc"
)
EXPECTED_YEAR = 2024
REQUIRE_FULL_YEAR = False
RTOL = 1e-6
ATOL = 1e-6


def _error(message: str) -> None:
    print(f"[FAIL] {message}")


def _ok(message: str) -> None:
    print(f"[OK]   {message}")


def validate_dataset(
    ds: xr.Dataset,
    expected_year: int | None,
    require_full_year: bool,
    rtol: float,
    atol: float,
) -> bool:
    valid = True

    required_vars = {"wind_power_mw", "total_wind_power_mw"}
    missing_vars = required_vars.difference(ds.data_vars)
    if missing_vars:
        _error(f"Missing required variable(s): {sorted(missing_vars)}")
        valid = False
    else:
        _ok("Required variables are present")

    required_dims = {"time", "site"}
    missing_dims = required_dims.difference(ds.dims)
    if missing_dims:
        _error(f"Missing required dimension(s): {sorted(missing_dims)}")
        valid = False
    else:
        _ok("Required dimensions are present")

    if "wind_power_mw" in ds.data_vars:
        if ds["wind_power_mw"].dims != ("time", "site"):
            _error(
                f"wind_power_mw dims are {ds['wind_power_mw'].dims}, expected ('time', 'site')"
            )
            valid = False
        else:
            _ok("wind_power_mw has expected dims")

    if "total_wind_power_mw" in ds.data_vars:
        if ds["total_wind_power_mw"].dims != ("time",):
            _error(
                f"total_wind_power_mw dims are {ds['total_wind_power_mw'].dims}, expected ('time',)"
            )
            valid = False
        else:
            _ok("total_wind_power_mw has expected dims")

    if "time" in ds.coords:
        times = ds["time"].values
        if times.size == 0:
            _error("time coordinate is empty")
            valid = False
        else:
            diffs = np.diff(times.astype("datetime64[ns]"))
            if np.any(diffs <= np.timedelta64(0, "ns")):
                _error("time coordinate is not strictly increasing")
                valid = False
            else:
                _ok("time coordinate is strictly increasing")

            if np.unique(times).size != times.size:
                _error("time coordinate contains duplicates")
                valid = False
            else:
                _ok("time coordinate has no duplicates")

            if expected_year is not None:
                years = times.astype("datetime64[Y]").astype(int) + 1970
                bad_year_count = int(np.sum(years != expected_year))
                if bad_year_count > 0:
                    _error(
                        f"Found {bad_year_count} timestamp(s) outside expected year {expected_year}"
                    )
                    valid = False
                else:
                    _ok(f"All timestamps are in expected year {expected_year}")

            if require_full_year and expected_year is not None:
                is_leap = (expected_year % 4 == 0 and expected_year % 100 != 0) or (
                    expected_year % 400 == 0
                )
                expected_hours = 8784 if is_leap else 8760
                if times.size != expected_hours:
                    _error(
                        f"Expected {expected_hours} hourly timestamps for full year, found {times.size}"
                    )
                    valid = False
                else:
                    _ok(f"Full-year hourly coverage detected ({expected_hours} points)")

    if "site" in ds.coords:
        site_values = ds["site"].values
        if site_values.size == 0:
            _error("site coordinate is empty")
            valid = False
        else:
            site_names = np.asarray(site_values, dtype=str)
            empty_names = np.where(np.char.strip(site_names) == "")[0]
            if empty_names.size > 0:
                _error(f"Found empty site name(s) at index positions {empty_names.tolist()}")
                valid = False
            else:
                _ok("site names are non-empty")

            if np.unique(site_names).size != site_names.size:
                _error("site coordinate contains duplicate names")
                valid = False
            else:
                _ok("site names are unique")

    for var in ["wind_power_mw", "total_wind_power_mw"]:
        if var in ds.data_vars:
            values = ds[var].values
            if not np.issubdtype(values.dtype, np.number):
                _error(f"{var} is not numeric (dtype={values.dtype})")
                valid = False
                continue

            if np.isnan(values).any():
                _error(f"{var} contains NaN values")
                valid = False
            else:
                _ok(f"{var} contains no NaN values")

            if np.isinf(values).any():
                _error(f"{var} contains infinite values")
                valid = False
            else:
                _ok(f"{var} contains no infinite values")

            if np.nanmin(values) < -1e-9:
                _error(f"{var} contains negative values (minimum={np.nanmin(values):.6f})")
                valid = False
            else:
                _ok(f"{var} is non-negative")

    if all(v in ds.data_vars for v in ["wind_power_mw", "total_wind_power_mw"]):
        summed = ds["wind_power_mw"].sum(dim="site").values
        total = ds["total_wind_power_mw"].values
        close = np.allclose(summed, total, rtol=rtol, atol=atol, equal_nan=False)
        if not close:
            max_abs = float(np.max(np.abs(summed - total)))
            _error(
                "total_wind_power_mw does not match sum(wind_power_mw over site); "
                f"max absolute difference={max_abs:.6e}"
            )
            valid = False
        else:
            _ok("total_wind_power_mw matches sum over sites")

    if expected_year is not None:
        year_attr = ds.attrs.get("year")
        if year_attr is None:
            _error("Global attribute 'year' is missing")
            valid = False
        else:
            try:
                year_attr_int = int(year_attr)
                if year_attr_int != expected_year:
                    _error(
                        f"Global attr year={year_attr_int} does not match expected year={expected_year}"
                    )
                    valid = False
                else:
                    _ok("Global attribute 'year' matches expected year")
            except (TypeError, ValueError):
                _error(f"Global attribute 'year' is not an integer-like value: {year_attr!r}")
                valid = False

    return valid


def main() -> None:
    if not OUTPUT_FILE.exists():
        _error(f"File not found: {OUTPUT_FILE}")
        raise SystemExit(2)

    print(f"Reading: {OUTPUT_FILE}")
    with xr.open_dataset(OUTPUT_FILE, engine="h5netcdf") as ds:
        valid = validate_dataset(
            ds=ds,
            expected_year=EXPECTED_YEAR,
            require_full_year=REQUIRE_FULL_YEAR,
            rtol=RTOL,
            atol=ATOL,
        )

    if valid:
        print("\nValidation PASSED")
        raise SystemExit(0)
    else:
        print("\nValidation FAILED")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
