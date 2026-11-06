#!/usr/bin/env python3
"""Check a regenerated dataset against the release it derives from.

For each month, in the grid files:
- protected variables have identical compressed chunks in the old and new files;
- grid-wide, pv_power_mw + pv_power_mw_distributed equals the sum of pv_power_mw_2025 in each hour;
- per country, the sum over the country's cells is compared with its pv_power_mw_2025. Cells shared
  with a neighbouring country contain both countries' output, so this check reports rather than asserts.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

import h5py
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import regenerate_distributed_grid as rdg

# float32 grid values lose about 1e-7 of each cell's value, which accumulates over many cells.
GLOBAL_TOLERANCE_MW = 5.0
GLOBAL_TOLERANCE_RELATIVE = 1e-4


def raw_chunk_digest(dset: h5py.Dataset) -> str:
    digest = hashlib.sha256()
    for index in range(dset.id.get_num_chunks()):
        info = dset.id.get_chunk_info(index)
        filter_mask, raw = dset.id.read_direct_chunk(info.chunk_offset)
        digest.update(str(info.chunk_offset).encode())
        digest.update(str(filter_mask).encode())
        digest.update(bytes(raw))
    return digest.hexdigest()


def country_masks(geometry: dict[str, rdg.AreaGeometry], shape: tuple[int, int]) -> dict[str, np.ndarray]:
    masks: dict[str, np.ndarray] = {}
    for info in geometry.values():
        mask = masks.setdefault(info.country, np.zeros(shape, dtype=bool))
        mask[info.farm_y, info.farm_x] = True
        if info.weight is not None:
            mask[info.weight_y, info.weight_x] = True
    return masks


def verify_month(task: tuple) -> tuple[dict, list[dict]]:
    year, month, source_root, target_root, cache_path = task
    name = f"{month:02d}_{year}_pv_wind_grid.nc"
    source = source_root / "per-farm-production" / str(year) / name
    target = target_root / "per-farm-production" / str(year) / name
    series = target_root / "country-aggregated-production" / str(year) / f"{month:02d}_{year}_pv_wind_country_timeseries.nc"
    source_series = source_root / "country-aggregated-production" / str(year) / series.name
    cache = rdg.load_geometry(cache_path)
    geometry = cache["areas"]

    summary: dict = {"Year": year, "Month": month, "protected_chunks_identical": True}
    with h5py.File(source, "r") as old, h5py.File(target, "r") as new:
        for variable in rdg.COPIED_VARIABLES:
            same = raw_chunk_digest(old[variable]) == raw_chunk_digest(new[variable])
            summary["protected_chunks_identical"] &= same
        summary["coordinates_identical"] = all(
            np.array_equal(old[name_][()], new[name_][()]) for name_ in rdg.COORDINATE_VARIABLES
        )

        areas, fleet_totals = rdg.read_area_series(series)
        _, source_totals = rdg.read_area_series(source_series)
        summary["series_identical"] = bool(np.array_equal(fleet_totals, source_totals))

        hours, ny, nx = new["pv_power_mw"].shape
        masks = country_masks(geometry, (ny, nx))
        by_country_expected: dict[str, np.ndarray] = {}
        for index, area in enumerate(areas):
            country = geometry[area].country
            by_country_expected[country] = by_country_expected.get(country, 0.0) + fleet_totals[:, index]

        global_sum = np.zeros(hours, dtype=np.float64)
        by_country_sum = {country: np.zeros(hours, dtype=np.float64) for country in masks}
        for start in range(0, hours, rdg.SLAB_HOURS):
            slab = new["pv_power_mw"][start : start + rdg.SLAB_HOURS].astype(np.float64)
            slab += new[rdg.DISTRIBUTED_VARIABLE][start : start + rdg.SLAB_HOURS]
            global_sum[start : start + slab.shape[0]] = slab.sum(axis=(1, 2))
            for country, mask in masks.items():
                by_country_sum[country][start : start + slab.shape[0]] = slab[:, mask].sum(axis=1)

    expected_total = fleet_totals.sum(axis=1)
    error = np.abs(global_sum - expected_total)
    limit = np.maximum(GLOBAL_TOLERANCE_MW, GLOBAL_TOLERANCE_RELATIVE * expected_total)
    summary["global_max_error_mw"] = float(error.max())
    summary["global_max_relative_error"] = float(np.max(error / np.maximum(expected_total, 1.0)))
    summary["global_closure_pass"] = bool(np.all(error <= limit))

    rows = []
    for country, expected in by_country_expected.items():
        got = by_country_sum[country]
        total = float(np.sum(expected))
        rows.append(
            {
                "Year": year,
                "Month": month,
                "Country": country,
                "expected_mwh": total,
                "cell_sum_mwh": float(got.sum()),
                "energy_relative_error": float(abs(got.sum() - total) / total) if total > 0 else 0.0,
                "max_hourly_error_mw": float(np.abs(got - expected).max()),
            }
        )
    return summary, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--years", nargs="+", type=int, default=list(range(1995, 2026)))
    parser.add_argument("--months", nargs="+", type=int, default=list(range(1, 13)))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--out-prefix", type=Path, required=True)
    args = parser.parse_args()

    tasks = [(y, m, args.source_root, args.target_root, args.geometry) for y in args.years for m in args.months]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(verify_month, tasks))

    args.out_prefix.parent.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame([item[0] for item in results])
    countries = pd.DataFrame([row for item in results for row in item[1]])
    summary.to_csv(args.out_prefix.with_name(args.out_prefix.name + "_months.csv"), index=False)
    countries.to_csv(args.out_prefix.with_name(args.out_prefix.name + "_countries.csv"), index=False)

    print(f"Months checked: {len(summary)}")
    for column in ("protected_chunks_identical", "coordinates_identical", "series_identical", "global_closure_pass"):
        print(f"{column}: {int(summary[column].sum())}/{len(summary)}")
    print(f"Largest grid-wide hourly error: {summary['global_max_error_mw'].max():.3f} MW")
    print(countries.groupby("Country")["energy_relative_error"].max().sort_values(ascending=False).head(15).to_string())


if __name__ == "__main__":
    main()
