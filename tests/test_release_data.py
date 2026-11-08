"""Checks on the regenerated release. They are skipped where the dataset is not available.

Set CERFRES_RELEASE_ROOT to the new dataset folder and CERFRES_PREVIOUS_ROOT to the previous one.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
import factor_history as fh

RELEASE = Path(os.environ.get("CERFRES_RELEASE_ROOT", config.OUTPUT_ROOT))
PREVIOUS = Path(os.environ.get("CERFRES_PREVIOUS_ROOT", config.DATA_ROOT / "highres-renewable-dataset" / "uncalibrated"))
UK = "United Kingdom (UK)"
YEARS = range(1995, 2026)

pytestmark = pytest.mark.skipif(
    not (RELEASE / "correction_factors").is_dir() or not (PREVIOUS / "country-aggregated-production").is_dir(),
    reason="Release data not available",
)


def load_factors(root: Path, path_of=fh.factor_file_path) -> pd.DataFrame:
    frames = []
    for year in YEARS:
        for month in range(1, 13):
            frame = pd.read_csv(path_of(root, year, month))
            frames.append(frame.assign(Year=year, Month=month))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="module")
def factors() -> pd.DataFrame:
    return load_factors(RELEASE / "correction_factors")


@pytest.fixture(scope="module")
def merged(factors) -> pd.DataFrame:
    """Joined with the source set: the factors written next to the previous country series."""
    source = load_factors(PREVIOUS / "country-aggregated-production", fh.series_factor_file_path)
    return factors.merge(source, on=["Area", "Year", "Month"], suffixes=("", "_previous"), validate="one_to_one")


def _is_fallback(frame: pd.DataFrame) -> np.ndarray:
    return np.array(
        [fh.requires_fallback(a, y, m) for a, y, m in zip(frame["Area"], frame["Year"], frame["Month"])], dtype=bool
    )


def test_file_columns_keep_the_published_order(factors):
    with fh.factor_file_path(RELEASE / "correction_factors", 2023, 7).open(encoding="utf-8") as fin:
        header = next(csv.reader(fin))
    assert header == ["Area", "PV_Factor", "Wind_Factor", "PV_Status", "Wind_Status"]


def test_only_known_status_values(factors):
    assert set(factors["PV_Status"]) <= set(fh.ALL_STATUSES)
    assert set(factors["Wind_Status"]) <= set(fh.ALL_STATUSES)


def test_factor_set_is_complete(factors):
    assert factors.groupby(["Year", "Month"]).ngroups == 372
    assert factors["Area"].nunique() == 47
    assert len(factors) == 372 * 47


def test_non_fallback_values_are_numerically_identical(merged):
    observed = merged[~_is_fallback(merged)]
    assert np.array_equal(observed["PV_Factor"].to_numpy(), observed["PV_Factor_previous"].to_numpy())
    assert np.array_equal(observed["Wind_Factor"].to_numpy(), observed["Wind_Factor_previous"].to_numpy())


def test_uk_wind_fallback_has_no_step_at_june_2021(factors):
    uk = factors[factors["Area"] == UK].sort_values(["Year", "Month"])
    after = uk[(uk["Year"] > 2021) | ((uk["Year"] == 2021) & (uk["Month"] >= 6))]
    before = uk[(uk["Year"] == 2021) & (uk["Month"] == 5)]
    assert after["Wind_Factor"].between(0.40, 0.60).all()
    assert (after["Wind_Status"] == fh.STATUS_HISTORICAL_FALLBACK).all()
    june = after.iloc[0]["Wind_Factor"]
    assert abs(june / before.iloc[0]["Wind_Factor"] - 1.0) < 0.1


def test_fallback_is_constant_for_each_calendar_month(factors):
    pre_2015 = factors[factors["Year"] < 2015]
    for column in ("PV_Factor", "Wind_Factor"):
        assert pre_2015.groupby(["Area", "Month"])[column].nunique().max() == 1


def test_fallback_rows_equal_formula_on_observed_rows(factors):
    rows = []
    for technology, (factor_col, status_col) in fh.TECHNOLOGY_COLUMNS.items():
        rows.append(
            pd.DataFrame(
                {
                    "Area": factors["Area"],
                    "Technology": technology,
                    "Year": factors["Year"],
                    "Month": factors["Month"],
                    "Factor": factors[factor_col],
                    "Status": factors[status_col],
                }
            )
        )
    history = fh.FactorHistory(pd.concat(rows, ignore_index=True))
    fallback_rows = factors[(factors["Year"] == 2000) & (factors["PV_Status"] == fh.STATUS_HISTORICAL_FALLBACK)]
    assert len(fallback_rows) > 100
    for _, row in fallback_rows.iterrows():
        assert row["PV_Factor"] == history.fallback(row["Area"], "PV", int(row["Month"])).value


def test_screened_observations_are_marked(factors):
    netherlands = factors[(factors["Area"] == "Netherlands (NL)") & (factors["Year"] == 2023)]
    assert (netherlands["PV_Status"] == fh.STATUS_INVALID_OBSERVATION).all()


def test_rule_one_checksums_are_identical():
    before = RELEASE / "checksums" / "rule1_before.csv"
    after_source = RELEASE / "checksums" / "rule1_after_source.csv"
    after_release = RELEASE / "checksums" / "rule1_after_release.csv"
    if not (before.exists() and after_source.exists() and after_release.exists()):
        pytest.skip("Checksum files not available")
    reference = pd.read_csv(before)
    pd.testing.assert_frame_equal(reference, pd.read_csv(after_source))
    pd.testing.assert_frame_equal(reference, pd.read_csv(after_release))
