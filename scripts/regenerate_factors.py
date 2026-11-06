#!/usr/bin/env python3
"""Rewrite the factor files with status columns and corrected fallback values.

Factors do not enter the published series, so no simulation is needed. Observed rows keep
their exact values. Fallback rows (all areas before 2015, the UK after May 2021) are recomputed
from the observed rows of the same factor set.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import factor_history as fh

YEARS = range(1995, 2026)
MONTHS = range(1, 13)


def read_published(root: Path) -> pd.DataFrame:
    """All published factor rows in long form, keeping each file's area order."""
    frames = []
    for year in YEARS:
        for month in MONTHS:
            frame = pd.read_csv(fh.factor_file_path(root, year, month))
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
    parser.add_argument("--published", type=Path, required=True, help="Existing correction_factors folder")
    parser.add_argument("--scan", type=Path, required=True, help="Output of build_factor_qa.py scan")
    parser.add_argument("--out", type=Path, required=True, help="New correction_factors folder")
    parser.add_argument("--changes", type=Path, required=True, help="CSV of old and new values of changed rows")
    args = parser.parse_args()

    if args.out.resolve() == args.published.resolve():
        raise ValueError("--out must differ from --published")

    published = read_published(args.published)
    scan = pd.read_csv(args.scan)[["Area", "Technology", "Year", "Month", "modelled_asbuilt_mwh", "modelled_2025_mwh"]]
    table = published.merge(scan, on=["Area", "Technology", "Year", "Month"], how="left", validate="one_to_one")
    if table["modelled_asbuilt_mwh"].isna().any():
        raise ValueError("The scan does not cover every published factor row")

    regenerated = recompute_fallback_rows(classify_observed_period(table))
    write_factor_files(regenerated, args.out)

    changes = regenerated.assign(Published=published["Factor"].to_numpy())
    changes = changes[
        changes["Is_Fallback"] & ~np.isclose(changes["Factor"], changes["Published"], rtol=1e-12, atol=0.0)
    ][["Area", "Technology", "Year", "Month", "Published", "Factor", "Status"]].rename(columns={"Factor": "New"})
    args.changes.parent.mkdir(parents=True, exist_ok=True)
    changes.to_csv(args.changes, index=False)

    observed = regenerated[~regenerated["Is_Fallback"]]
    unchanged = np.array_equal(
        observed["Factor"].to_numpy(dtype=np.float64),
        published.loc[observed.index, "Factor"].to_numpy(dtype=np.float64),
    )
    if not unchanged:
        raise RuntimeError("A non-fallback factor changed value")
    print(regenerated.groupby(["Technology", "Status"]).size().to_string())
    print(f"{len(changes)} fallback rows changed; non-fallback values are unchanged.", flush=True)


if __name__ == "__main__":
    main()
