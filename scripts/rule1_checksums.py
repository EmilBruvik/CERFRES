#!/usr/bin/env python3
"""SHA-256 checksums of the grid variables that must never change between releases.

The checksum is taken over the decoded float32 values (not the compressed bytes), so
it compares the data and is unaffected by file layout or compression settings.

Example:
    python scripts/rule1_checksums.py /path/to/uncalibrated/per-farm-production \
        --years 1995 2015 2023 --out before.csv --workers 4
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

import h5py

PROTECTED_VARIABLES = ("wind_power_mw_onshore", "wind_power_mw_offshore", "pv_power_mw")
SLAB_HOURS = 24


def checksum_file(path: Path) -> list[tuple[str, str, str, str]]:
    rows = []
    with h5py.File(path, "r") as src:
        for name in PROTECTED_VARIABLES:
            dset = src[name]
            digest = hashlib.sha256()
            digest.update(str(dset.shape).encode())
            digest.update(str(dset.dtype).encode())
            for start in range(0, dset.shape[0], SLAB_HOURS):
                digest.update(dset[start : start + SLAB_HOURS].tobytes())
            rows.append((path.parent.name, path.name, name, digest.hexdigest()))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("grid_root", type=Path, help="Folder holding {year}/{mm}_{year}_pv_wind_grid.nc")
    parser.add_argument("--years", nargs="+", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    files: list[Path] = []
    for year in args.years:
        found = sorted((args.grid_root / str(year)).glob("[0-9][0-9]_*_pv_wind_grid.nc"))
        if len(found) != 12:
            raise ValueError(f"Expected 12 grid files for {year}, found {len(found)}")
        files.extend(found)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(checksum_file, files))

    with args.out.open("w", newline="", encoding="utf-8") as fout:
        writer = csv.writer(fout)
        writer.writerow(["year", "file", "variable", "sha256"])
        for rows in results:
            writer.writerows(rows)
    print(f"Wrote {sum(len(r) for r in results)} checksums to {args.out}", flush=True)


if __name__ == "__main__":
    main()
