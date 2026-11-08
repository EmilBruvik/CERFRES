#!/usr/bin/env python3
"""Rewrite the factor files with status columns and corrected fallback values.

Factors do not enter the published series, so no simulation is needed.

- Observed rows keep the exact values of the source set. Since v1.2.0 the source is the set
  written next to the country series (`country-aggregated-production/{year}/correction_factors`),
  because it was calculated from the published series. The set published with v1.1 in
  `correction_factors/` came from an earlier run and does not match the series.
- Fallback rows (all areas before 2015, the UK after May 2021) are recomputed from the observed
  rows of the source set.
- The changes file lists every row whose value differs from the previously published set.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import factor_history as fh

YEARS = range(1995, 2026)
MONTHS = range(1, 13)
LAYOUTS: dict[str, Callable[[Path, int, int], Path]] = {
    "release": fh.factor_file_path,
    "series": fh.series_factor_file_path,
}


def read_factor_set(root: Path, layout: str) -> pd.DataFrame:
    """All factor rows of one set in long form, keeping each file's area order."""
    path_of = LAYOUTS[layout]
    frames = []
    for year in YEARS:
        for month in MONTHS:
            frame = pd.read_csv(path_of(root, year, month))
            frame["row"] = np.arange(len(frame))
            for technology, (factor_col, _) in fh.TECHNOLOGY_COLUMNS.items():
                frames.append(
                    pd.DataFrame(
                        {
                            "Area": frame["Area"],
                            "Technology": technology,
                            "Year": year,
                            "Month": month,
                            "row": frame["row"],
                            "Factor": frame[factor_col],
                        }
                    )
                )
    return pd.concat(frames, ignore_index=True)


def classify_observed_period(table: pd.DataFrame) -> pd.DataFrame:
    """Status of every non-fallback row. Fallback rows are placeholders until recomputed."""
    statuses = []
    for area, technology, year, month, factor, energy in zip(
        table["Area"], table["Technology"], table["Year"], table["Month"], table["Factor"], table["modelled_asbuilt_mwh"]
    ):
        if fh.requires_fallback(area, year, month):
            statuses.append(fh.STATUS_HISTORICAL_FALLBACK)
        else:
            statuses.append(fh.resolve_status(area, technology, year, month, factor, energy))
    return table.assign(Status=statuses)


def recompute_fallback_rows(table: pd.DataFrame) -> pd.DataFrame:
    history = fh.FactorHistory(table[["Area", "Technology", "Year", "Month", "Factor", "Status"]])
    out = table.copy()
    is_fallback = np.array(
        [fh.requires_fallback(a, y, m) for a, y, m in zip(out["Area"], out["Year"], out["Month"])], dtype=bool
    )
    new_factor = out["Factor"].to_numpy(dtype=np.float64).copy()
    new_status = out["Status"].to_numpy(dtype=object).copy()
    for index in np.flatnonzero(is_fallback):
        row = out.iloc[index]
        if not row["modelled_2025_mwh"] > 0.0:
            # The area has no fleet in any year; the simulation keeps its value in this case.
            new_status[index] = fh.STATUS_NO_MODELLED_FLEET
            continue
        result = history.fallback(row["Area"], row["Technology"], int(row["Month"]))
        new_factor[index] = result.value
        new_status[index] = fh.resolve_status(
            row["Area"], row["Technology"], int(row["Year"]), int(row["Month"]),
            result.value, row["modelled_asbuilt_mwh"], result.status,
        )
    return out.assign(Factor=new_factor, Status=new_status, Is_Fallback=is_fallback)


def write_factor_files(table: pd.DataFrame, out_root: Path) -> None:
    wide = table.pivot(index=["Year", "Month", "row", "Area"], columns="Technology", values=["Factor", "Status"])
    wide.columns = [f"{'PV' if tech == 'PV' else 'Wind'}_{kind}" for kind, tech in wide.columns]
    wide = wide.reset_index().sort_values(["Year", "Month", "row"])
    for (year, month), group in wide.groupby(["Year", "Month"]):
        path = fh.factor_file_path(out_root, int(year), int(month))
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = group[fh.FACTOR_FILE_COLUMNS].copy()
        frame["PV_Factor"] = frame["PV_Factor"].astype(np.float64)
        frame["Wind_Factor"] = frame["Wind_Factor"].astype(np.float64)
        frame.to_csv(path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Factor set whose observed values are kept")
    parser.add_argument("--source-layout", choices=sorted(LAYOUTS), default="series")
    parser.add_argument("--previous", type=Path, required=True, help="Previously published correction_factors folder")
    parser.add_argument("--scan", type=Path, required=True, help="Output of build_factor_qa.py scan")
    parser.add_argument("--out", type=Path, required=True, help="New correction_factors folder")
    parser.add_argument("--changes", type=Path, required=True, help="CSV of rows that differ from the previous set")
    args = parser.parse_args()

    if args.out.resolve() in (args.source.resolve(), args.previous.resolve()):
        raise ValueError("--out must differ from --source and --previous")

    source = read_factor_set(args.source, args.source_layout)
    previous = read_factor_set(args.previous, "release")
    keys = ["Area", "Technology", "Year", "Month", "row"]
    if not source[keys].equals(previous[keys]):
        raise ValueError("The source and previous sets do not list the same areas in the same order")

    scan = pd.read_csv(args.scan)[["Area", "Technology", "Year", "Month", "modelled_asbuilt_mwh", "modelled_2025_mwh"]]
    table = source.merge(scan, on=["Area", "Technology", "Year", "Month"], how="left", validate="one_to_one")
    if table["modelled_asbuilt_mwh"].isna().any():
        raise ValueError("The scan does not cover every factor row")

    regenerated = recompute_fallback_rows(classify_observed_period(table))
    write_factor_files(regenerated, args.out)

    observed = regenerated[~regenerated["Is_Fallback"]]
    if not np.array_equal(
        observed["Factor"].to_numpy(dtype=np.float64),
        source.loc[observed.index, "Factor"].to_numpy(dtype=np.float64),
    ):
        raise RuntimeError("A non-fallback factor differs from the source set")

    changes = regenerated.assign(
        Previous=previous["Factor"].to_numpy(),
        Source=source["Factor"].to_numpy(),
        Kind=np.where(regenerated["Is_Fallback"], "fallback", "observed_period"),
    )
    changes = changes[~np.isclose(changes["Factor"], changes["Previous"], rtol=1e-12, atol=0.0)]
    changes = changes[["Area", "Technology", "Year", "Month", "Kind", "Previous", "Factor", "Status"]].rename(
        columns={"Factor": "New"}
    )
    args.changes.parent.mkdir(parents=True, exist_ok=True)
    changes.to_csv(args.changes, index=False)

    print(regenerated.groupby(["Technology", "Status"]).size().to_string())
    print(changes.groupby("Kind").size().to_string())
    print("Non-fallback values equal the source set.", flush=True)


if __name__ == "__main__":
    main()
