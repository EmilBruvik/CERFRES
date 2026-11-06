#!/usr/bin/env python3
"""Rewrite the monthly grid files with a corrected pv_power_mw_distributed.

No weather data are needed. The country series pv_power_mw_2025 equals the farm sum of an area
times its capacity scale, and the scale depends only on the trackers. The distributed part of
the fixed 2025 fleet therefore follows from pv_power_mw_2025 alone.

All other variables are copied as raw compressed HDF5 chunks, so their stored bytes do not change.
Country-series files are copied with only the `note` attribute replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pickle
import shutil
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

import h5py
import netCDF4
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

COPIED_VARIABLES = ("wind_power_mw_onshore", "wind_power_mw_offshore", "pv_power_mw")
DISTRIBUTED_VARIABLE = "pv_power_mw_distributed"
COORDINATE_VARIABLES = ("time", "y", "x", "latitude", "longitude")
SLAB_HOURS = 24


@dataclass(frozen=True)
class AreaGeometry:
    country: str
    capacity_scale: float
    farm_y: np.ndarray
    farm_x: np.ndarray
    weight_y: np.ndarray | None
    weight_x: np.ndarray | None
    weight: np.ndarray | None
    weight_source: str  # "population", "farm_capacity" or "none"


def grid_hash(latitude: np.ndarray, longitude: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(np.asarray(latitude, dtype=np.float64).tobytes())
    digest.update(np.asarray(longitude, dtype=np.float64).tobytes())
    return digest.hexdigest()


def read_grid_coordinates(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with h5py.File(path, "r") as src:
        return src["latitude"][()], src["longitude"][()]


def build_geometry(sample_grid: Path, cache_path: Path) -> None:
    """Capacity scales and cell weights of every area, shared by all months."""
    import config
    import weather_energy_monthly as wem

    latitude, longitude = read_grid_coordinates(sample_grid)
    indexer = wem.GridIndexer(latitude, longitude)
    with tempfile.TemporaryDirectory(prefix="cerfres_geometry_") as tmp:
        tmp_path = Path(tmp)
        runner = wem.MonthlyRunner(tmp_path / "a", tmp_path / "b", tmp_path / "c", n_jobs_pv=1)

    geometry: dict[str, AreaGeometry] = {}
    for country, area in zip(wem.countries_tracker, wem.countries_codes):
        fleet, scale = wem.select_pv_fleet(runner.pv.df_main, runner.pv.df_distributed, country, area)
        if len(fleet):
            farm_y, farm_x = indexer.map_points(fleet["Latitude"].to_numpy(), fleet["Longitude"].to_numpy())
            fleet = fleet.assign(y_idx=farm_y, x_idx=farm_x)
        else:
            farm_y, farm_x = np.array([], dtype=int), np.array([], dtype=int)

        population = runner._country_population_cell_weights(country, indexer)
        weights = population if population is not None else runner._farm_capacity_cell_weights(fleet)
        source = "population" if population is not None else ("farm_capacity" if weights is not None else "none")
        weight_y, weight_x, weight = weights if weights is not None else (None, None, None)
        geometry[area] = AreaGeometry(country, float(scale), farm_y, farm_x, weight_y, weight_x, weight, source)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("wb") as fout:
        plain = {area: asdict(info) for area, info in geometry.items()}
        pickle.dump({"grid_hash": grid_hash(latitude, longitude), "areas": plain}, fout)
    print(f"Wrote geometry of {len(geometry)} areas to {cache_path}", flush=True)
    print(f"Config tracker: {config.SOLAR_TRACKER_DISTRIBUTED_CSV}", flush=True)


def load_geometry(cache_path: Path) -> dict:
    with cache_path.open("rb") as fin:
        cache = pickle.load(fin)
    cache["areas"] = {area: AreaGeometry(**info) for area, info in cache["areas"].items()}
    return cache


def read_area_series(path: Path, variable: str = "pv_power_mw_2025") -> tuple[list[str], np.ndarray]:
    """Return area names and a (time, area) array from a country-series file."""
    with h5py.File(path, "r") as src:
        raw_names = src["area"][()]
        values = src[variable][()]
    names = [name.decode("utf-8") if isinstance(name, bytes) else str(name) for name in raw_names]
    return names, values


def distributed_area_totals(fleet_total: np.ndarray, capacity_scale: float) -> np.ndarray:
    """Distributed PV of one area, from its fixed-fleet total and capacity scale."""
    from weather_energy_monthly import distributed_pv_residual

    return distributed_pv_residual(fleet_total, fleet_total / capacity_scale)


def build_distributed_grid(
    areas: list[str],
    fleet_totals: np.ndarray,
    geometry: dict[str, AreaGeometry],
    shape: tuple[int, int, int],
) -> tuple[np.ndarray, dict[str, float]]:
    """Spread each area's distributed PV over its cells. Returns the grid and any dropped energy."""
    grid = np.zeros(shape, dtype=np.float32)
    dropped: dict[str, float] = {}
    for index, area in enumerate(areas):
        info = geometry[area]
        residual = distributed_area_totals(fleet_totals[:, index], info.capacity_scale)
        if not np.any(residual > 0):
            continue
        if info.weight is None:
            dropped[area] = float(residual.sum())
            continue
        grid[:, info.weight_y, info.weight_x] += (residual[:, None] * info.weight[None, :]).astype(np.float32)
    return grid, dropped


def create_skeleton(
    src: h5py.File,
    target: Path,
    shuffle: bool,
    complevel: int,
    time_values: np.ndarray | None = None,
) -> None:
    """Create an output with the source's coordinates, chunking and attributes.

    `time_values` replaces the time coordinate, for a file that spans several source files.
    """
    with netCDF4.Dataset(target, "w", format="NETCDF4") as dst:
        for name in ("time", "y", "x"):
            length = len(time_values) if name == "time" and time_values is not None else src[name].shape[0]
            dst.createDimension(name, length)
        for name in COORDINATE_VARIABLES:
            dset = src[name]
            dims = ("time",) if name == "time" else ((name,) if name in ("y", "x") else ("y", "x"))
            var = dst.createVariable(
                name, dset.dtype, dims, zlib=dset.compression == "gzip", complevel=dset.compression_opts or 4,
                shuffle=bool(dset.shuffle), chunksizes=dset.chunks,
            )
            for key, value in dset.attrs.items():
                if not key.startswith(("DIMENSION", "REFERENCE", "_Netcdf4", "NAME", "CLASS", "_FillValue")):
                    var.setncattr(key, value.decode() if isinstance(value, bytes) else value)
            var[:] = time_values if name == "time" and time_values is not None else dset[()]

        for name in (*COPIED_VARIABLES, DISTRIBUTED_VARIABLE):
            dset = src[name]
            fill = dset.attrs.get("_FillValue")
            fill_value = None if fill is None else np.asarray(fill).ravel()[0]
            copied = name in COPIED_VARIABLES
            var = dst.createVariable(
                name, dset.dtype, ("time", "y", "x"), zlib=True,
                complevel=dset.compression_opts if copied else complevel,
                shuffle=bool(dset.shuffle) if copied else shuffle,
                chunksizes=dset.chunks, fill_value=fill_value,
            )
            for key, value in dset.attrs.items():
                if not key.startswith(("DIMENSION", "REFERENCE", "_Netcdf4", "NAME", "CLASS", "_FillValue")):
                    var.setncattr(key, value.decode() if isinstance(value, bytes) else value)


def copy_raw_chunks(source: h5py.Dataset, target: h5py.Dataset) -> int:
    """Copy compressed chunks unchanged, so the stored bytes stay the same."""
    count = source.id.get_num_chunks()
    for index in range(count):
        info = source.id.get_chunk_info(index)
        filter_mask, raw = source.id.read_direct_chunk(info.chunk_offset)
        target.id.write_direct_chunk(info.chunk_offset, raw, filter_mask)
    return count


def regenerate_grid_file(
    source_grid: Path,
    source_series: Path,
    target: Path,
    geometry_cache: dict,
    shuffle: bool = True,
    complevel: int = 4,
) -> dict:
    """Write one monthly grid file and return its dropped energy per area."""
    from weather_energy_monthly import DISTRIBUTED_PV_DESCRIPTION

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".tmp_{target.name}")
    try:
        with h5py.File(source_grid, "r") as src:
            if grid_hash(src["latitude"][()], src["longitude"][()]) != geometry_cache["grid_hash"]:
                raise ValueError(f"Grid coordinates of {source_grid} differ from the geometry cache")
            shape = src[DISTRIBUTED_VARIABLE].shape
            areas, fleet_totals = read_area_series(source_series)
            if fleet_totals.shape[0] != shape[0]:
                raise ValueError(f"Time length differs between {source_grid} and {source_series}")
            grid, dropped = build_distributed_grid(areas, fleet_totals, geometry_cache["areas"], shape)

            create_skeleton(src, tmp_path, shuffle, complevel)
            with h5py.File(tmp_path, "r+") as dst:
                for name in COPIED_VARIABLES:
                    copy_raw_chunks(src[name], dst[name])

        with netCDF4.Dataset(tmp_path, "r+") as dst:
            var = dst.variables[DISTRIBUTED_VARIABLE]
            for start in range(0, shape[0], SLAB_HOURS):
                var[start : start + SLAB_HOURS, :, :] = grid[start : start + SLAB_HOURS]
            var.setncattr("description", DISTRIBUTED_PV_DESCRIPTION)
        os.replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return dropped


def copy_series_file(source: Path, target: Path) -> None:
    """Copy a country-series file, replacing only the note attribute."""
    from weather_energy_monthly import SERIES_NOTE

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".tmp_{target.name}")
    try:
        shutil.copyfile(source, tmp_path)
        with h5py.File(tmp_path, "r+") as dst:
            dst.attrs["note"] = SERIES_NOTE
        os.replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _month_task(task: tuple) -> tuple[int, int, dict]:
    year, month, source_root, target_root, cache_path, shuffle, complevel = task
    name_grid = f"{month:02d}_{year}_pv_wind_grid.nc"
    name_series = f"{month:02d}_{year}_pv_wind_country_timeseries.nc"
    source_series = source_root / "country-aggregated-production" / str(year) / name_series
    copy_series_file(source_series, target_root / "country-aggregated-production" / str(year) / name_series)

    target_grid = target_root / "per-farm-production" / str(year) / name_grid
    if target_grid.exists():
        return year, month, {}
    dropped = regenerate_grid_file(
        source_root / "per-farm-production" / str(year) / name_grid,
        source_series,
        target_grid,
        load_geometry(cache_path),
        shuffle=shuffle,
        complevel=complevel,
    )
    print(f"Wrote {target_grid.name} ({target_grid.stat().st_size / 1e9:.2f} GB)", flush=True)
    return year, month, dropped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True, help="Existing dataset folder (read only)")
    parser.add_argument("--target-root", type=Path, required=True, help="New dataset folder")
    parser.add_argument("--geometry", type=Path, required=True, help="Geometry cache, created if missing")
    parser.add_argument("--years", nargs="+", type=int, default=list(range(1995, 2026)))
    parser.add_argument("--months", nargs="+", type=int, default=list(range(1, 13)))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--no-shuffle", action="store_true", help="Do not apply the HDF5 shuffle filter")
    parser.add_argument("--complevel", type=int, default=4)
    args = parser.parse_args()

    if args.source_root.resolve() == args.target_root.resolve():
        raise ValueError("--target-root must differ from --source-root")

    if not args.geometry.exists():
        sample = args.source_root / "per-farm-production" / str(args.years[0]) / f"01_{args.years[0]}_pv_wind_grid.nc"
        build_geometry(sample, args.geometry)

    tasks = [
        (year, month, args.source_root, args.target_root, args.geometry, not args.no_shuffle, args.complevel)
        for year in args.years
        for month in args.months
    ]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(_month_task, tasks))

    dropped_total: dict[str, float] = {}
    for _, _, dropped in results:
        for area, energy in dropped.items():
            dropped_total[area] = dropped_total.get(area, 0.0) + energy
    print(f"Finished {len(results)} months. Areas with dropped distributed energy (MWh): {dropped_total}", flush=True)


if __name__ == "__main__":
    main()
