#!/usr/bin/env python3
"""Combine a dataset's monthly files into one zip per year.

Each zip holds the year's country series, grid and correction factors. Existing zips are skipped,
so an interrupted run can be restarted.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import h5py
import netCDF4
import numpy as np
import xarray as xr

import regenerate_distributed_grid as rdg


CHUNK_CACHE_BYTES = 512 * 1024 * 1024


def monthly_files(folder: Path, suffix: str) -> list[Path]:
    files = sorted(folder.glob(f"[0-9][0-9]_*{suffix}"))
    if len(files) != 12:
        raise ValueError(f"Expected 12 monthly files in {folder}, found {len(files)}")
    return files


def combine_netcdf(files: list[Path], output: Path) -> None:
    combined = xr.open_mfdataset(
        [str(path) for path in files],
        combine="nested",
        concat_dim="time",
        data_vars="minimal",
        coords="minimal",
        compat="override",
        combine_attrs="override",
        chunks={"time": 24},
        engine="h5netcdf",
    )
    try:
        combined = combined.sortby("time")
        combined.to_netcdf(output, engine="h5netcdf")
    finally:
        combined.close()


def read_time_in_common_units(files: list[Path]) -> list[np.ndarray]:
    """Each monthly file counts time from its own start, so convert to the first file's units."""
    parts = []
    target_units = None
    target_calendar = None
    for path in files:
        with netCDF4.Dataset(path, "r") as src:
            var = src.variables["time"]
            if target_units is None:
                target_units, target_calendar = var.units, var.calendar
            dates = netCDF4.num2date(
                var[:].data, var.units, var.calendar, only_use_cftime_datetimes=False, only_use_python_datetimes=True
            )
            converted = netCDF4.date2num(dates, target_units, target_calendar)
            parts.append(np.rint(converted).astype(var.dtype))
    return parts


def combine_grids(files: list[Path], output: Path) -> None:
    """Join monthly grids into one file with a uniform chunk layout.

    Time chunks differ between months of different length, so values are read and recompressed
    in 24-hour slabs. Every month has a whole number of days, so slabs match the output chunks.
    """
    time_parts = read_time_in_common_units(files)
    time_values = np.concatenate(time_parts)
    if not np.all(np.diff(time_values) > 0):
        raise ValueError(f"Time axis is not increasing across {files[0].parent}")

    with h5py.File(files[0], "r") as first:
        rdg.create_skeleton(
            first,
            output,
            shuffle=bool(first[rdg.DISTRIBUTED_VARIABLE].shuffle),
            complevel=first[rdg.DISTRIBUTED_VARIABLE].compression_opts,
            time_values=time_values,
        )
    variables = (*rdg.COPIED_VARIABLES, rdg.DISTRIBUTED_VARIABLE)
    with h5py.File(output, "r+") as dst:
        offset = 0
        for path, part in zip(files, time_parts):
            with h5py.File(path, "r", rdcc_nbytes=CHUNK_CACHE_BYTES) as src:
                for name in variables:
                    for start in range(0, len(part), rdg.SLAB_HOURS):
                        stop = start + rdg.SLAB_HOURS
                        dst[name][offset + start : offset + stop] = src[name][start:stop]
            offset += len(part)


def combine_csv(files: list[Path], output: Path) -> None:
    writer = None
    fieldnames = None
    with output.open("w", newline="", encoding="utf-8") as fout:
        for path in files:
            with path.open("r", newline="", encoding="utf-8") as fin:
                reader = csv.DictReader(fin)
                if writer is None:
                    fieldnames = reader.fieldnames
                    writer = csv.DictWriter(fout, fieldnames=fieldnames)
                    writer.writeheader()
                elif reader.fieldnames != fieldnames:
                    raise ValueError(f"CSV columns differ in {path}")
                writer.writerows(reader)


def build_year(task: tuple) -> tuple[int, str, int]:
    year, root, out_dir, version, tmp_root = task
    archive = out_dir / f"CERFRES_Europe_hourly_{year}_v{version}.zip"
    if not archive.exists():
        series = monthly_files(root / "country-aggregated-production" / str(year), "_pv_wind_country_timeseries.nc")
        grids = monthly_files(root / "per-farm-production" / str(year), "_pv_wind_grid.nc")
        factors = monthly_files(root / "correction_factors" / str(year), "_pv_wind_country_factors.csv")

        with tempfile.TemporaryDirectory(prefix=f"cerfres_{year}_", dir=tmp_root) as tmp:
            tmp_dir = Path(tmp)
            series_out = tmp_dir / f"{year}_country_aggregated_uncalibrated.nc"
            grid_out = tmp_dir / f"{year}_per_farm_uncalibrated.nc"
            factors_out = tmp_dir / f"{year}_correction_factors_uncalibrated.csv"
            combine_netcdf(series, series_out)
            combine_grids(grids, grid_out)
            combine_csv(factors, factors_out)

            tmp_archive = tmp_dir / archive.name
            with zipfile.ZipFile(tmp_archive, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                for path in (series_out, grid_out, factors_out):
                    zf.write(path, arcname=path.name)
            shutil.move(str(tmp_archive), archive)

    digest = hashlib.md5()
    with archive.open("rb") as fin:
        for block in iter(lambda: fin.read(1 << 24), b""):
            digest.update(block)
    print(f"{archive.name} {archive.stat().st_size / 1e9:.2f} GB", flush=True)
    return year, digest.hexdigest(), archive.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Dataset folder with the monthly files")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--years", nargs="+", type=int, default=list(range(1995, 2026)))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--tmp", type=Path, default=None, help="Scratch folder for intermediate files")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    tmp_root = args.tmp or args.out
    tmp_root.mkdir(parents=True, exist_ok=True)
    tasks = [(year, args.root, args.out, args.version, tmp_root) for year in args.years]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(build_year, tasks))

    with (args.out / "MD5SUMS.txt").open("w", encoding="utf-8") as fout:
        for year, md5, _ in sorted(results):
            fout.write(f"{md5}  CERFRES_Europe_hourly_{year}_v{args.version}.zip\n")
    print(f"Total: {sum(size for _, _, size in results) / 1e9:.1f} GB in {len(results)} zips", flush=True)


if __name__ == "__main__":
    main()
